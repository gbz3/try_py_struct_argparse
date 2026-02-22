import argparse
import ast
import codecs
import json
import struct
import sys
from typing import List, Tuple

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
            ast.UnaryOp, ast.Not,
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
    return parser.parse_args()

def validate_args(args: argparse.Namespace) -> Tuple[struct.Struct, List[str]]:
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

    # フィールド名のパース
    field_names = [f.strip() for f in args.fields.split(",") if f.strip()]
    if not field_names:
        sys.exit("エラー: フィールド名が指定されていません。")

    # フォーマットの要素数（パディング 'x' を除く）を計算
    # struct.Struct には要素数を直接取得するプロパティがないため、ダミーデータでアンパックして要素数を数える
    dummy_data = b'\x00' * st.size
    try:
        unpacked_dummy = st.unpack(dummy_data)
        expected_fields_count = len(unpacked_dummy)
    except struct.error as e:
        sys.exit(f"エラー: フォーマットの検証に失敗しました: {e}")

    if len(field_names) != expected_fields_count:
        sys.exit(
            f"エラー: フィールド名の数 ({len(field_names)}) が "
            f"フォーマットの要素数 ({expected_fields_count}) と一致しません。"
        )

    if args.condition:
        if not is_safe_expression(args.condition, field_names):
            sys.exit("エラー: 抽出条件の式が安全ではありません。")

    return st, field_names

def main():
    args = parse_args()
    st, field_names = validate_args(args)
    
    # 標準入力からバイナリモードで読み込む
    stdin_binary = sys.stdin.buffer
    
    # 条件式が指定されている場合はコンパイルしておく
    compiled_condition = compile(args.condition, '<string>', 'eval') if args.condition else None

    while True:
        chunk = stdin_binary.read(st.size)
        if not chunk:
            break # EOF
        
        if len(chunk) != st.size:
            sys.exit(f"エラー: 読み込んだデータサイズ ({len(chunk)} bytes) がフォーマットのサイズ ({st.size} bytes) と一致しません。")

        try:
            unpacked_data = st.unpack(chunk)
        except struct.error as e:
            sys.exit(f"エラー: データのアンパックに失敗しました: {e}")

        # フィールド名と値をマッピングし、bytes型はデコードする
        record = {}
        for name, value in zip(field_names, unpacked_data):
            if isinstance(value, bytes):
                try:
                    # null文字(\x00)が含まれている場合は除去してからデコード
                    value = value.rstrip(b'\x00').decode(args.encoding)
                except UnicodeDecodeError as e:
                    sys.exit(f"エラー: フィールド '{name}' のデコードに失敗しました ({args.encoding}): {e}")
            record[name] = value

        # 抽出条件の評価
        if compiled_condition:
            try:
                # recordのキー(フィールド名)をローカル変数としてevalに渡す
                if not eval(compiled_condition, {"__builtins__": {}}, record):
                    continue # 条件に合致しない場合はスキップ
            except Exception as e:
                sys.exit(f"エラー: 抽出条件の評価中に例外が発生しました: {e}")

        # 出力処理
        if args.output == "binary":
            sys.stdout.buffer.write(chunk)
        elif args.output == "json":
            print(json.dumps(record, ensure_ascii=False))
        else: # dict
            print(record)

if __name__ == "__main__":
    main()
