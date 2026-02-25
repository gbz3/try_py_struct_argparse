import argparse
import ast
import codecs
import json
import re
import struct
import sys
from typing import List, Optional, Tuple

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

def decode_bcd(data: bytes, sign_position: str) -> int:
    """
    パック10進数 (BCD) を整数に変換します。
    sign_position:
      'tail' : 最終バイトの下位ニブルが符号 (方式A/COBOL, デフォルト)
      'head' : 先頭バイトの上位ニブルが符号 (方式B)
      'none' : 符号なし、全ニブルが数字 (方式C)
    符号ニブル: C(0xC)=正, D(0xD)=負, F(0xF)=符号なし(正)
    """
    if sign_position == 'tail':
        sign_nibble = data[-1] & 0x0F
        sign = -1 if sign_nibble == 0xD else 1
        # 全バイトの上位ニブル + 最終バイト以外の下位ニブルが数字
        nibbles = []
        for i, byte in enumerate(data):
            nibbles.append((byte >> 4) & 0x0F)
            if i < len(data) - 1:
                nibbles.append(byte & 0x0F)
        value = int(''.join(str(n) for n in nibbles))
        return sign * value
    elif sign_position == 'head':
        sign_nibble = (data[0] >> 4) & 0x0F
        sign = -1 if sign_nibble == 0xD else 1
        # 先頭バイトの下位ニブル以降が数字
        nibbles = []
        for i, byte in enumerate(data):
            if i == 0:
                nibbles.append(byte & 0x0F)
            else:
                nibbles.append((byte >> 4) & 0x0F)
                nibbles.append(byte & 0x0F)
        value = int(''.join(str(n) for n in nibbles))
        return sign * value
    else:  # 'none'
        nibbles = []
        for byte in data:
            nibbles.append((byte >> 4) & 0x0F)
            nibbles.append(byte & 0x0F)
        return int(''.join(str(n) for n in nibbles))

def decode_zone(data: bytes, sign_position: str) -> int:
    """
    ゾーン10進数を整数に変換します。
    各バイトの下位ニブルが数字、上位ニブルがゾーン(0xF) または符号。
    sign_position:
      'tail' : 最終バイトの上位ニブルが符号 (COBOL/EBCDIC デフォルト)
      'head' : 先頭バイトの上位ニブルが符号
      'none' : 符号なし、全バイト上位ニブルはゾーン
    符号ニブル: C(0xC)=正, D(0xD)=負, F(0xF)=符号なし(正)
    """
    if sign_position == 'tail':
        sign_nibble = (data[-1] >> 4) & 0x0F
        sign = -1 if sign_nibble == 0xD else 1
        digits = [byte & 0x0F for byte in data]
        value = int(''.join(str(d) for d in digits))
        return sign * value
    elif sign_position == 'head':
        sign_nibble = (data[0] >> 4) & 0x0F
        sign = -1 if sign_nibble == 0xD else 1
        digits = [byte & 0x0F for byte in data]
        value = int(''.join(str(d) for d in digits))
        return sign * value
    else:  # 'none'
        digits = [byte & 0x0F for byte in data]
        return int(''.join(str(d) for d in digits))

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
            ast.Constant, # 数値、文字列、True, False, None
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
    return parser.parse_args()

_VALID_SIGN_POSITIONS = {'tail', 'head', 'none'}

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

    return st, field_specs

def main():
    args = parse_args()
    st, field_specs = validate_args(args)

    # 標準入力からバイナリモードで読み込む
    stdin_binary = sys.stdin.buffer
    
    # 条件式が指定されている場合はコンパイルしておく
    compiled_condition = compile(args.condition, '<string>', 'eval') if args.condition else None

    output_count = 0
    input_rec_no = 0
    while True:
        chunk = stdin_binary.read(st.size)
        if not chunk:
            break # EOF

        input_rec_no += 1
        
        if len(chunk) != st.size:
            sys.exit(f"エラー: 読み込んだデータサイズ ({len(chunk)} bytes) がフォーマットのサイズ ({st.size} bytes) と一致しません。")

        try:
            unpacked_data = st.unpack(chunk)
        except struct.error as e:
            sys.exit(f"エラー: データのアンパックに失敗しました: {e}")

        # フィールド名と値をマッピングし、bytes型はデコードする
        record = {}
        for (name, annotation, sign_override), value in zip(field_specs, unpacked_data):
            if isinstance(value, bytes):
                if annotation == 'bcd':
                    sign = sign_override if sign_override else args.bcd_sign
                    try:
                        value = decode_bcd(value, sign)
                    except Exception as e:
                        sys.exit(f"エラー: フィールド '{name}' のBCDデコードに失敗しました: {e}")
                elif annotation == 'zone':
                    sign = sign_override if sign_override else args.zone_sign
                    try:
                        value = decode_zone(value, sign)
                    except Exception as e:
                        sys.exit(f"エラー: フィールド '{name}' のゾーン10進デコードに失敗しました: {e}")
                else:
                    try:
                        # null文字(\x00)が含まれている場合は除去してからデコード
                        value = value.rstrip(b'\x00').decode(args.encoding)
                    except UnicodeDecodeError as e:
                        sys.exit(f"エラー: フィールド '{name}' のデコードに失敗しました ({args.encoding}): {e}")
            record[name] = value

        # 抽出条件の評価 (_rec_no を常に参照可能にする)
        if compiled_condition:
            try:
                eval_locals = {**record, '_rec_no': input_rec_no}
                if not eval(compiled_condition, {"__builtins__": {}}, eval_locals):
                    continue # 条件に合致しない場合はスキップ
            except Exception as e:
                sys.exit(f"エラー: 抽出条件の評価中に例外が発生しました: {e}")

        # 出力処理
        if args.output == "binary":
            sys.stdout.buffer.write(chunk)
        else:
            if args.record_num:
                record = {'_rec_no': input_rec_no, **record}
            if args.output == "json":
                print(json.dumps(record, ensure_ascii=False))
            else: # dict
                print(record)

        output_count += 1
        if args.max_records is not None and output_count >= args.max_records:
            break

if __name__ == "__main__":
    main()
