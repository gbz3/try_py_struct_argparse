import argparse
import ast
import codecs
import json
import multiprocessing
import os
import re
import struct
import sys
from typing import Any, Dict, List, Optional, Tuple

# ワーカー1プロセスあたりが処理するレコード数。大きいほどI/Oが効率的になるが
# メモリ使用量が増える。チューニングの目安として変更可能。
BATCH_SIZE = 256

def get_format_type_codes(fmt: str) -> List[str]:
    """
    structフォーマット文字列から、各アンパック要素の型コードリストを返します（パディング 'x' を除く）。
    例: '>I3sh' -> ['I', 's', 'h']
        '3I'   -> ['I', 'I', 'I']
    """
    fmt_body = fmt.lstrip('@=<>!')
    type_codes = []
    for match in re.finditer(r'(\d*)([a-zA-Z?])', fmt_body):
        count_str, code = match.groups()
        count = int(count_str) if count_str else 1
        if code == 'x':
            continue  # パディング、値なし
        elif code in ('s', 'p'):
            type_codes.append(code)  # Ns は1つの bytes 値
        else:
            type_codes.extend([code] * count)  # 3I は3つの int 値
    return type_codes

_DEFAULT_NEGA_NIBBLES: frozenset = frozenset({0x7})

def decode_bcd(data: bytes, sign_position: str, nega_nibbles: frozenset = _DEFAULT_NEGA_NIBBLES) -> int:
    """
    パック10進数 (BCD) を整数に変換します。
    sign_position:
      'tail' : 最終バイトの下位ニブルが符号 (方式A/COBOL, デフォルト)
      'head' : 先頭バイトの上位ニブルが符号 (方式B)
      'none' : 符号なし、全ニブルが数字 (方式C)
    nega_nibbles: 負符号とみなすニブル値の集合 (デフォルト: {0x7})
      nega_nibbles に一致→負、それ以外はすべて正とみなす。
    """
    if sign_position == 'tail':
        sign_nibble = data[-1] & 0x0F
        sign = -1 if sign_nibble in nega_nibbles else 1
        # 全バイトの上位ニブル + 最終バイト以外の下位ニブルが数字
        value = 0
        for i, byte in enumerate(data):
            value = value * 10 + ((byte >> 4) & 0x0F)
            if i < len(data) - 1:
                value = value * 10 + (byte & 0x0F)
        return sign * value
    elif sign_position == 'head':
        sign_nibble = (data[0] >> 4) & 0x0F
        sign = -1 if sign_nibble in nega_nibbles else 1
        # 先頭バイトの下位ニブル以降が数字
        value = 0
        for i, byte in enumerate(data):
            if i == 0:
                value = byte & 0x0F
            else:
                value = value * 10 + ((byte >> 4) & 0x0F)
                value = value * 10 + (byte & 0x0F)
        return sign * value
    else:  # 'none'
        value = 0
        for byte in data:
            value = value * 10 + ((byte >> 4) & 0x0F)
            value = value * 10 + (byte & 0x0F)
        return value

def decode_zone(data: bytes, sign_position: str, nega_nibbles: frozenset = _DEFAULT_NEGA_NIBBLES) -> int:
    """
    ゾーン10進数を整数に変換します。
    各バイトの下位ニブルが数字、上位ニブルがゾーン(0xF) または符号。
    sign_position:
      'tail' : 最終バイトの上位ニブルが符号 (COBOL/EBCDIC デフォルト)
      'head' : 先頭バイトの上位ニブルが符号
      'none' : 符号なし、全バイト上位ニブルはゾーン
    nega_nibbles: 負符号とみなすニブル値の集合 (デフォルト: {0x7})
      nega_nibbles に一致→負、それ以外はすべて正とみなす。
    """
    if sign_position == 'tail':
        sign_nibble = (data[-1] >> 4) & 0x0F
        sign = -1 if sign_nibble in nega_nibbles else 1
    elif sign_position == 'head':
        sign_nibble = (data[0] >> 4) & 0x0F
        sign = -1 if sign_nibble in nega_nibbles else 1
    else:  # 'none'
        sign = 1
    value = 0
    for byte in data:
        value = value * 10 + (byte & 0x0F)
    return sign * value

def parse_field_specs(fields_str: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """
    フィールド名、型アノテーション、符号位置オーバーライドをパースします。
    例:
      'id,price:bcd,name'           -> [('id', None, None), ('price', 'bcd', None), ('name', None, None)]
      'id,price:bcd:tail,amt:zone:head' -> [('id', None, None), ('price', 'bcd', 'tail'), ('amt', 'zone', 'head')]
    """
    specs = []
    for f in fields_str.split(','):
        f = f.strip()
        if not f:
            continue
        parts = f.split(':')
        name = parts[0].strip()
        annotation = parts[1].strip() if len(parts) >= 2 else None
        sign_override = parts[2].strip() if len(parts) >= 3 else None
        specs.append((name, annotation, sign_override))
    return specs

def is_safe_expression(expr: str, allowed_names: List[str]) -> bool:
    """
    ASTを使用して、指定されたPython式が安全かどうかを検証します。
    許可されるノード: 比較、論理演算、算術演算、リテラル、指定された変数名
    """
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        # 許可するノードの型
        if isinstance(node, (
            ast.Expression,
            ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
            ast.BoolOp, ast.And, ast.Or,
            ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
            ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv, ast.Pow,
            ast.Constant,       # 数値、文字列、True, False, None（3.8+）
            # Python 3.8 旧形式の互換ノード (3.12 で削除済みのため getattr で取得)
            *[n for n in [
                getattr(ast, 'Str', None),
                getattr(ast, 'Num', None),
                getattr(ast, 'Bytes', None),
                getattr(ast, 'NameConstant', None),
            ] if n is not None],
            ast.Load
        )):
            continue
        elif isinstance(node, ast.Name):
            # 変数名は、フィールド名として指定されたもののみ許可
            if node.id not in allowed_names:
                print(f"エラー: 許可されていない変数名 '{node.id}' が使用されています。", file=sys.stderr)
                return False
        else:
            # 許可されていないノード（関数呼び出し、属性アクセスなど）
            print(f"エラー: 許可されていない構文 '{type(node).__name__}' が使用されています。", file=sys.stderr)
            return False
    return True

# ---------------------------------------------------------------------------
# マルチプロセス ワーカー
# ---------------------------------------------------------------------------

# ワーカープロセスが共有するモジュールレベルのグローバル変数
_worker_st: Optional[struct.Struct] = None
_worker_field_specs: Optional[List[Tuple[str, Optional[str], Optional[str]]]] = None
_worker_encoding: str = 'cp932'
_worker_bcd_sign: str = 'tail'
_worker_zone_sign: str = 'tail'
_worker_compiled_cond: Any = None
_worker_on_decode_error: str = 'abort'
_worker_bcd_nega_nibbles: frozenset = _DEFAULT_NEGA_NIBBLES
_worker_zone_nega_nibbles: frozenset = _DEFAULT_NEGA_NIBBLES


def _worker_init(
    fmt: str,
    field_specs: List[Tuple[str, Optional[str], Optional[str]]],
    encoding: str,
    bcd_sign: str,
    zone_sign: str,
    condition_str: Optional[str],
    on_decode_error: str,
    bcd_nega_nibbles: frozenset,
    zone_nega_nibbles: frozenset,
) -> None:
    """各ワーカープロセスの起動時に一度だけ呼ばれる初期化関数。"""
    global _worker_st, _worker_field_specs, _worker_encoding
    global _worker_bcd_sign, _worker_zone_sign, _worker_compiled_cond
    global _worker_on_decode_error
    global _worker_bcd_nega_nibbles, _worker_zone_nega_nibbles
    _worker_st = struct.Struct(fmt)
    _worker_field_specs = field_specs
    _worker_encoding = encoding
    _worker_bcd_sign = bcd_sign
    _worker_zone_sign = zone_sign
    _worker_compiled_cond = compile(condition_str, '<string>', 'eval') if condition_str else None
    _worker_on_decode_error = on_decode_error
    _worker_bcd_nega_nibbles = bcd_nega_nibbles
    _worker_zone_nega_nibbles = zone_nega_nibbles


def _process_batch(
    args_tuple: Tuple[bytes, int],
) -> List[Tuple[int, bytes, Optional[Dict[str, Any]]]]:
    """バイト列のバッチを受け取り、レコードごとにデコード・条件評価を行う。

    Returns:
        list of (rec_no, raw_chunk, record)
        record が None の場合は条件に合致しなかったことを示す。
    """
    batch_bytes, start_rec_no = args_tuple
    rec_size = _worker_st.size  # type: ignore[union-attr]
    n_records = len(batch_bytes) // rec_size
    results: List[Tuple[int, bytes, Optional[Dict[str, Any]]]] = []

    for i in range(n_records):
        rec_no = start_rec_no + i
        chunk = batch_bytes[i * rec_size:(i + 1) * rec_size]

        unpacked_data = _worker_st.unpack(chunk)  # type: ignore[union-attr]

        record: Dict[str, Any] = {}
        decode_error = False
        for (name, annotation, sign_override), value in zip(_worker_field_specs, unpacked_data):  # type: ignore[arg-type]
            if isinstance(value, bytes):
                if annotation == 'bcd':
                    sign = sign_override if sign_override else _worker_bcd_sign
                    value = decode_bcd(value, sign, _worker_bcd_nega_nibbles)
                elif annotation == 'zone':
                    sign = sign_override if sign_override else _worker_zone_sign
                    value = decode_zone(value, sign, _worker_zone_nega_nibbles)
                else:
                    if _worker_on_decode_error == 'ignore':
                        value = value.rstrip(b'\x00').decode(_worker_encoding, errors='ignore')
                    elif _worker_on_decode_error in ('skip', 'null'):
                        try:
                            value = value.rstrip(b'\x00').decode(_worker_encoding)
                        except Exception as e:
                            print(f"警告: レコード {rec_no}, フィールド '{name}': {e}", file=sys.stderr)
                            if _worker_on_decode_error == 'skip':
                                decode_error = True
                                break
                            else:  # null
                                value = None
                    else:  # abort
                        value = value.rstrip(b'\x00').decode(_worker_encoding)
            record[name] = value
        if decode_error:
            results.append((rec_no, chunk, None))
            continue

        if _worker_compiled_cond is not None:
            eval_locals = {**record, '_rec_no': rec_no}
            if not eval(_worker_compiled_cond, {"__builtins__": {}}, eval_locals):
                results.append((rec_no, chunk, None))
                continue

        results.append((rec_no, chunk, record))

    return results


def _batch_generator(
    stdin_binary,
    rec_size: int,
):
    """stdin をバッチ単位で読み込んで (batch_bytes, start_rec_no) を yield する。"""
    rec_no = 1
    while True:
        raw = stdin_binary.read(rec_size * BATCH_SIZE)
        if not raw:
            break
        n = len(raw) // rec_size
        remainder = len(raw) % rec_size
        if remainder:
            sys.exit(
                f"エラー: 読み込んだデータサイズ ({len(raw)} bytes) が "
                f"レコードサイズ ({rec_size} bytes) の倍数ではありません。"
            )
        if n > 0:
            yield (raw, rec_no)
            rec_no += n


# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="固定長レコードのバイナリファイルを標準入力から読み込み、指定フォーマットでアンパックして出力します。"
    )
    parser.add_argument(
        "format",
        help="structモジュールの書式文字列 (例: '>I10sh')"
    )
    parser.add_argument(
        "fields",
        help="アンパックした各フィールド名 (カンマ区切り, 例: 'id,name,age')"
    )
    parser.add_argument(
        "-c", "--condition",
        help="抽出条件のPython式 (例: 'age > 20'). 指定したフィールド名を変数として使用可能."
    )
    parser.add_argument(
        "-o", "--output",
        choices=["dict", "json", "binary"],
        default="dict",
        help="出力形式 (デフォルト: dict)"
    )
    parser.add_argument(
        "-e", "--encoding",
        default="cp932",
        help="文字列(bytes)をデコードする際のエンコーディング (デフォルト: cp932)"
    )
    parser.add_argument(
        "--bcd-sign",
        choices=["tail", "head", "none"],
        default="tail",
        help="BCD符号の位置: tail=最終バイト下位ニブル(デフォルト/COBOL), head=先頭バイト上位ニブル, none=符号なし"
    )
    parser.add_argument(
        "--zone-sign",
        choices=["tail", "head", "none"],
        default="tail",
        help="ゾーン10進符号の位置: tail=最終バイト上位ニブル(デフォルト/COBOL), head=先頭バイト上位ニブル, none=符号なし"
    )
    parser.add_argument(
        "-n", "--max-records",
        type=int,
        default=None,
        metavar="N",
        help="出力レコードの最大件数。N件に達した時点で処理を中止します。(デフォルト: 無制限)"
    )
    parser.add_argument(
        "--record-num",
        action="store_true",
        default=False,
        help="出力レコードの先頭に入力レコード番号 '_rec_no'（1始まり）を付与します。-o binary では無効。"
             " --condition 内では --record-num 指定の有無に関わらず '_rec_no' を常に参照できます。"
    )
    parser.add_argument(
        "--on-decode-error",
        choices=["abort", "skip", "null", "ignore"],
        default="abort",
        dest="on_decode_error",
        help="デコードエラー発生時の動作: abort=即時中止（デフォルト）、skip=レコードをスキップ、"
             "null=フィールドをNoneにして継続、ignore=デコード不能バイトを除去して継続"
             "（文字列フィールドのみ有効、BCD/Zone には影響なし）"
    )
    parser.add_argument(
        "--bcd-nega-nibble",
        default="0x7",
        dest="bcd_nega_nibble",
        metavar="HEX[,HEX...]",
        help="BCD の負符号とみなすニブル値（カンマ区切り16進数, デフォルト: 0x7）。"
             "例: 0xd  または  0x7,0xd"
    )
    parser.add_argument(
        "--zone-nega-nibble",
        default="0x7",
        dest="zone_nega_nibble",
        metavar="HEX[,HEX...]",
        help="Zone の負符号とみなすニブル値（カンマ区切り16進数, デフォルト: 0x7）。"
             "例: 0xd  または  0x7,0xd"
    )
    return parser.parse_args()

_VALID_SIGN_POSITIONS = {'tail', 'head', 'none'}

def parse_nibble_set(text: str, argname: str) -> frozenset:
    """
    カンマ区切りの16進数文字列を frozenset[int] に変換します。
    例: '0x7'     -> frozenset({7})
        '0x7,0xd' -> frozenset({7, 13})
    0〜15 の範囲外の値は sys.exit() でエラーを出します。
    """
    result = set()
    for token in text.split(','):
        token = token.strip()
        if not token:
            continue
        try:
            val = int(token, 16)
        except ValueError:
            sys.exit(f"エラー: {argname} の値 '{token}' は有効な16進数ではありません。")
        if not (0 <= val <= 15):
            sys.exit(f"エラー: {argname} の値 '{token}' はニブル値の範囲 (0x0〜0xf) を超えています。")
        result.add(val)
    if not result:
        sys.exit(f"エラー: {argname} に有効な値が指定されていません。")
    return frozenset(result)

def validate_args(args: argparse.Namespace) -> Tuple[struct.Struct, List[Tuple[str, Optional[str], Optional[str]]]]:
    # エンコーディングのチェック
    try:
        codecs.lookup(args.encoding)
    except LookupError:
        sys.exit(f"エラー: 指定されたエンコーディング '{args.encoding}' は利用できません。")

    # structフォーマットのコンパイルとチェック
    try:
        st = struct.Struct(args.format)
    except struct.error as e:
        sys.exit(f"エラー: 無効なstructフォーマットです '{args.format}': {e}")

    # フィールド名と型アノテーションのパース
    field_specs = parse_field_specs(args.fields)
    if not field_specs:
        sys.exit("エラー: フィールド名が指定されていません。")
    field_names = [name for name, *_ in field_specs]

    # フォーマットの型コードリストを取得（パディング 'x' を除く）
    # get_format_type_codes で要素数も確認できるため、ダミーアンパックは不要
    type_codes = get_format_type_codes(args.format)
    if len(field_specs) != len(type_codes):
        sys.exit(
            f"エラー: フィールド名の数 ({len(field_specs)}) が "
            f"フォーマットの要素数 ({len(type_codes)}) と一致しません。"
        )

    # :bcd / :zone アノテーションと型コードの整合チェック、sign_override の値チェック
    for i, (name, annotation, sign_override) in enumerate(field_specs):
        if annotation == 'bcd' and type_codes[i] not in ('s', 'p'):
            sys.exit(
                f"エラー: フィールド '{name}' に ':bcd' が指定されていますが、"
                f"フォーマットの型コード '{type_codes[i]}' はバイト列 ('s', 'p') ではありません。"
            )
        if annotation == 'zone' and type_codes[i] not in ('s', 'p'):
            sys.exit(
                f"エラー: フィールド '{name}' に ':zone' が指定されていますが、"
                f"フォーマットの型コード '{type_codes[i]}' はバイト列 ('s', 'p') ではありません。"
            )
        if sign_override is not None and sign_override not in _VALID_SIGN_POSITIONS:
            sys.exit(
                f"エラー: フィールド '{name}' の符号位置指定 '{sign_override}' は無効です。"
                f" 有効な値: {sorted(_VALID_SIGN_POSITIONS)}"
            )

    if args.condition:
        if not is_safe_expression(args.condition, field_names + ['_rec_no']):
            sys.exit("エラー: 抽出条件の式が安全ではありません。")

    # nega_nibble オプションのパース
    args.bcd_nega_nibbles = parse_nibble_set(args.bcd_nega_nibble, '--bcd-nega-nibble')
    args.zone_nega_nibbles = parse_nibble_set(args.zone_nega_nibble, '--zone-nega-nibble')

    return st, field_specs

def main():
    args = parse_args()
    st, field_specs = validate_args(args)

    stdin_binary = sys.stdin.buffer
    n_workers = os.cpu_count() or 1

    initargs = (
        args.format,
        field_specs,
        args.encoding,
        args.bcd_sign,
        args.zone_sign,
        args.condition,
        args.on_decode_error,
        args.bcd_nega_nibbles,
        args.zone_nega_nibbles,
    )

    output_count = 0
    done = False

    with multiprocessing.Pool(
        processes=n_workers,
        initializer=_worker_init,
        initargs=initargs,
    ) as pool:
        try:
            for batch_results in pool.imap(
                _process_batch,
                _batch_generator(stdin_binary, st.size),
            ):
                # バッチ内の出力をまとめて書き込む（システムコール削減）
                if args.output == "binary":
                    chunks = [
                        chunk
                        for _, chunk, record in batch_results
                        if record is not None
                    ]
                    # --max-records を考慮して先頭から必要分だけ抽出
                    if args.max_records is not None:
                        remaining = args.max_records - output_count
                        chunks = chunks[:remaining]
                    if chunks:
                        sys.stdout.buffer.write(b''.join(chunks))
                        output_count += len(chunks)
                else:
                    lines = []
                    for rec_no, chunk, record in batch_results:
                        if record is None:
                            continue
                        if args.record_num:
                            record = {'_rec_no': rec_no, **record}
                        if args.output == "json":
                            lines.append(json.dumps(record, ensure_ascii=False))
                        else:  # dict
                            lines.append(str(record))
                        output_count += 1
                        if args.max_records is not None and output_count >= args.max_records:
                            done = True
                            break
                    if lines:
                        sys.stdout.write('\n'.join(lines) + '\n')

                if done or (
                    args.max_records is not None and output_count >= args.max_records
                ):
                    pool.terminate()
                    break
        except Exception as e:
            pool.terminate()
            sys.exit(f"エラー: 処理中に例外が発生しました: {e}")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows exe 化時に必要
    main()
