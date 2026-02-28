import io
import struct
from unittest.mock import patch
import pytest

from main import is_safe_expression, validate_args, parse_args, main, decode_bcd, decode_zone, parse_field_specs, get_format_type_codes, parse_nibble_set

def test_is_safe_expression():
    allowed = ["id", "name", "age", "price"]
    # 正常な式
    assert is_safe_expression("age > 20", allowed) is True
    assert is_safe_expression("name == 'Alice' and id % 2 == 0", allowed) is True
    assert is_safe_expression("price > -1000", allowed) is True   # 負数リテラル
    assert is_safe_expression("price == -6789", allowed) is True  # 負数リテラル

    # 許可されていない変数
    assert is_safe_expression("unknown > 10", allowed) is False

    # 許可されていない構文（関数呼び出し、属性アクセスなど）
    assert is_safe_expression("print(age)", allowed) is False
    assert is_safe_expression("__import__('os').system('ls')", allowed) is False

def test_validate_args_success():
    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age"]):
        args = parse_args()
        st, field_specs = validate_args(args)
        assert st.format == ">I10sh"
        assert field_specs == [("id", None, None), ("name", None, None), ("age", None, None)]

def test_validate_args_mismatch():
    with patch("sys.argv", ["main.py", ">I10sh", "id,name"]):
        args = parse_args()
        with pytest.raises(SystemExit):
            validate_args(args)

def test_validate_args_invalid_encoding():
    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-e", "invalid_enc"]):
        args = parse_args()
        with pytest.raises(SystemExit):
            validate_args(args)

# --- get_format_type_codes ---

def test_get_format_type_codes_basic():
    assert get_format_type_codes('>I3sh') == ['I', 's', 'h']

def test_get_format_type_codes_multi_count():
    assert get_format_type_codes('3Ih') == ['I', 'I', 'I', 'h']

def test_get_format_type_codes_padding():
    # x はパディングなので要素なし
    assert get_format_type_codes('>I2xh') == ['I', 'h']

# --- :bcd on non-bytes field ---

def test_validate_args_bcd_on_non_bytes_field():
    # h (short int) に :bcd を付けた場合はエラーになるべき
    with patch("sys.argv", ["main.py", ">I3sh", "id,price:bcd,age:bcd"]):
        args = parse_args()
        with pytest.raises(SystemExit):
            validate_args(args)

# --- parse_field_specs ---

def test_parse_field_specs_no_annotation():
    assert parse_field_specs("id,name,age") == [("id", None, None), ("name", None, None), ("age", None, None)]

def test_parse_field_specs_with_bcd():
    assert parse_field_specs("id,price:bcd,name") == [("id", None, None), ("price", "bcd", None), ("name", None, None)]

def test_parse_field_specs_with_sign_override():
    assert parse_field_specs("id,price:bcd:tail,amt:zone:head") == [
        ("id", None, None),
        ("price", "bcd", "tail"),
        ("amt", "zone", "head"),
    ]

# --- invalid sign_override ---

def test_validate_args_invalid_sign_override():
    # 不正な符号位置指定はエラーになるべき
    with patch("sys.argv", ["main.py", ">I3s", "id,price:bcd:invalid"]):
        args = parse_args()
        with pytest.raises(SystemExit):
            validate_args(args)

# --- decode_bcd ---

def test_decode_bcd_tail_positive():
    # 0x01 0x23 0x4C -> +1234
    assert decode_bcd(b'\x01\x23\x4C', 'tail') == 1234

def test_decode_bcd_tail_negative():
    # 0x01 0x23 0x4D -> -1234 (tail, sign=D=負)
    assert decode_bcd(b'\x01\x23\x4D', 'tail', frozenset({0xD})) == -1234

def test_decode_bcd_tail_unsigned():
    # 0x01 0x23 0x4F -> +1234 (F=符号なし)
    assert decode_bcd(b'\x01\x23\x4F', 'tail') == 1234

def test_decode_bcd_head_positive():
    # 0xC0 0x12 0x34 -> +1234 (sign=C, digits=[0,1,2,3,4] -> '01234' -> 1234)
    # head: 3バイト = 1符号ニブル + 5桁ニブル
    assert decode_bcd(b'\xC0\x12\x34', 'head') == 1234

def test_decode_bcd_head_negative():
    # 0xD0 0x05 0x67 -> -567 (head, sign=D=負)
    assert decode_bcd(b'\xD0\x05\x67', 'head', frozenset({0xD})) == -567

def test_decode_bcd_none():
    # 0x12 0x34 -> 1234
    assert decode_bcd(b'\x12\x34', 'none') == 1234

# --- E2E with BCD ---

def test_main_e2e_bcd_dict():
    # フォーマット: >I3s (ID: 4bytes unsigned int, price: 3bytes BCD)
    fmt = ">I3s"
    price_bcd = b'\x01\x23\x4C'  # +1234
    data = struct.pack(fmt, 1, price_bcd)
    
    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()
    
    with patch("sys.argv", ["main.py", ">I3s", "id,price:bcd", "-o", "dict"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()
    
    output = stdout_mock.getvalue()
    assert "'price': 1234" in output

def test_main_e2e_bcd_per_field_sign():
    # フィールド毎の符号位置指定: price は :bcd:tail、discount は :bcd:head
    # price: 0x01 0x23 0x4C -> +1234 (tail)
    # discount: 0xD0 0x05 0x67 -> -567 (head)
    fmt = ">I3s3s"
    price_bcd    = b'\x01\x23\x4C'
    discount_bcd = b'\xD0\x05\x67'
    data = struct.pack(fmt, 1, price_bcd, discount_bcd)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I3s3s", "id,price:bcd:tail,discount:bcd:head", "-o", "dict",
                              "--bcd-nega-nibble", "0xd"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    output = stdout_mock.getvalue()
    assert "'price': 1234" in output
    assert "'discount': -567" in output


class MockStdin:
    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)

def test_main_e2e_dict():
    fmt = ">I10sh"
    data = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)
    data += struct.pack(fmt, 2, "Bob".encode("cp932"), 30)
    
    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()
    
    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-o", "dict"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()
        
    output = stdout_mock.getvalue()
    assert "'name': 'Alice'" in output
    assert "'name': 'Bob'" in output

def test_main_e2e_condition_json():
    fmt = ">I10sh"
    data = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)
    data += struct.pack(fmt, 2, "Bob".encode("cp932"), 30)
    
    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()
    
    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-c", "age > 25", "-o", "json"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()
        
    output = stdout_mock.getvalue().strip().split('\n')
    assert len(output) == 1
    assert '"name": "Bob"' in output[0]

class MockStdout:
    def __init__(self):
        self.buffer = io.BytesIO()

def test_main_e2e_max_records():
    fmt = ">I10sh"
    data = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)
    data += struct.pack(fmt, 2, "Bob".encode("cp932"), 30)
    data += struct.pack(fmt, 3, "Carol".encode("cp932"), 35)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-n", "2"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    lines = [line for line in stdout_mock.getvalue().strip().split("\n") if line]
    assert len(lines) == 2
    assert "'name': 'Alice'" in lines[0]
    assert "'name': 'Bob'" in lines[1]

def test_main_e2e_max_records_with_condition():
    # --condition でフィルタ後の出力件数が -n の上限に従うことを確認
    fmt = ">I10sh"
    data = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)
    data += struct.pack(fmt, 2, "Bob".encode("cp932"), 30)
    data += struct.pack(fmt, 3, "Carol".encode("cp932"), 35)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-c", "age > 25", "-n", "1"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    lines = [line for line in stdout_mock.getvalue().strip().split("\n") if line]
    assert len(lines) == 1
    assert "'name': 'Bob'" in lines[0]

def test_main_e2e_binary():
    fmt = ">I10sh"
    data1 = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)
    data2 = struct.pack(fmt, 2, "Bob".encode("cp932"), 30)
    
    stdin_mock = MockStdin(data1 + data2)
    stdout_mock = MockStdout()
    
    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-c", "age > 25", "-o", "binary"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()
        
    assert stdout_mock.buffer.getvalue() == data2

# --- decode_zone ---

def test_decode_zone_tail_positive():
    # 0xF1 0xF2 0xF3 0xC4 -> +1234 (tail, sign=C=正)
    assert decode_zone(b'\xF1\xF2\xF3\xC4', 'tail') == 1234

def test_decode_zone_tail_negative():
    # 0xF1 0xF2 0xF3 0xD4 -> -1234 (tail, sign=D=負)
    assert decode_zone(b'\xF1\xF2\xF3\xD4', 'tail', frozenset({0xD})) == -1234

def test_decode_zone_tail_unsigned():
    # 0xF1 0xF2 0xF3 0xF4 -> +1234 (tail, sign=F=符号なし→正)
    assert decode_zone(b'\xF1\xF2\xF3\xF4', 'tail') == 1234

def test_decode_zone_head_positive():
    # 0xC1 0xF2 0xF3 0xF4 -> +1234 (head, sign=C=正)
    assert decode_zone(b'\xC1\xF2\xF3\xF4', 'head') == 1234

def test_decode_zone_head_negative():
    # 0xD0 0xF5 0xF6 0xF7 -> -567 (head, sign=D=負)
    assert decode_zone(b'\xD0\xF5\xF6\xF7', 'head', frozenset({0xD})) == -567

def test_decode_zone_none():
    # 0xF1 0xF2 0xF3 0xF4 -> 1234 (符号なし)
    assert decode_zone(b'\xF1\xF2\xF3\xF4', 'none') == 1234

# --- :zone on non-bytes field ---

def test_validate_args_zone_on_non_bytes_field():
    # h (short int) に :zone を付けた場合はエラーになるべき
    with patch("sys.argv", ["main.py", ">I4sh", "id,amount:zone,age:zone"]):
        args = parse_args()
        with pytest.raises(SystemExit):
            validate_args(args)

# --- E2E with Zone decimal ---

def test_main_e2e_zone_dict():
    # フォーマット: >I4s (ID: 4bytes unsigned int, amount: 4bytes Zone decimal)
    fmt = ">I4s"
    # +1234: 0xF1 0xF2 0xF3 0xC4 (tail符号, sign=C=正)
    zone_amount = b'\xF1\xF2\xF3\xC4'
    data = struct.pack(fmt, 1, zone_amount)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I4s", "id,amount:zone", "-o", "dict"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    output = stdout_mock.getvalue()
    assert "'amount': 1234" in output

def test_main_e2e_zone_negative_dict():
    # フォーマット: >I4s (ID: 4bytes unsigned int, amount: 4bytes Zone decimal)
    fmt = ">I4s"
    # -5678: 0xF5 0xF6 0xF7 0xD8 (tail符号, sign=D=負)
    zone_amount = b'\xF5\xF6\xF7\xD8'
    data = struct.pack(fmt, 2, zone_amount)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I4s", "id,amount:zone", "-o", "dict",
                              "--zone-nega-nibble", "0xd"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    output = stdout_mock.getvalue()
    assert "'amount': -5678" in output

# --- --record-num ---

def test_main_e2e_record_num_dict():
    fmt = ">I10sh"
    data = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)
    data += struct.pack(fmt, 2, "Bob".encode("cp932"), 30)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "--record-num"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    lines = [line for line in stdout_mock.getvalue().strip().split("\n") if line]
    assert len(lines) == 2
    assert "'_rec_no': 1" in lines[0]
    assert "'_rec_no': 2" in lines[1]
    # _rec_no が先頭キーであることを確認
    assert lines[0].startswith("{'_rec_no': 1,")

def test_main_e2e_record_num_condition():
    # --record-num なしでも _rec_no を condition 内で参照できることの確認
    fmt = ">I10sh"
    data = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)
    data += struct.pack(fmt, 2, "Bob".encode("cp932"), 30)
    data += struct.pack(fmt, 3, "Carol".encode("cp932"), 35)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-c", "_rec_no == 2", "-o", "json"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    lines = [line for line in stdout_mock.getvalue().strip().split("\n") if line]
    assert len(lines) == 1
    assert '"name": "Bob"' in lines[0]

def test_main_e2e_record_num_skipped_count():
    # --condition でスキップされたレコードも入力番号にカウントされることの確認
    fmt = ">I10sh"
    data = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)  # age <= 25: スキップ
    data += struct.pack(fmt, 2, "Bob".encode("cp932"), 30)   # age > 25: 出力

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-c", "age > 25", "--record-num"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    lines = [line for line in stdout_mock.getvalue().strip().split("\n") if line]
    assert len(lines) == 1
    # Bob は入力2番目なので _rec_no == 2
    assert "'_rec_no': 2" in lines[0]

def test_main_e2e_record_num_not_in_binary():
    # binary 出力時は --record-num を指定してもバイナリに影響しない
    fmt = ">I10sh"
    data1 = struct.pack(fmt, 1, "Alice".encode("cp932"), 25)

    stdin_mock = MockStdin(data1)
    stdout_mock = MockStdout()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "-o", "binary", "--record-num"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    assert stdout_mock.buffer.getvalue() == data1

def test_main_e2e_on_decode_error_skip():
    # --on-decode-error skip: decode エラーのレコードがスキップされること
    # レコード2の name として cp932 で不正なバイト列を使用
    invalid_name = b'\x81\x07' + b'\x00' * 8
    data  = struct.pack(">I", 1) + "Alice".encode("cp932").ljust(10, b'\x00') + struct.pack(">h", 25)
    data += struct.pack(">I", 2) + invalid_name + struct.pack(">h", 30)
    data += struct.pack(">I", 3) + "Carol".encode("cp932").ljust(10, b'\x00') + struct.pack(">h", 35)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()
    stderr_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "--on-decode-error", "skip"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock), \
         patch("sys.stderr", stderr_mock):
        main()

    lines = [line for line in stdout_mock.getvalue().strip().split("\n") if line]
    # レコード2はスキップされ2件のみ出力
    assert len(lines) == 2
    assert "Alice" in lines[0]
    assert "Carol" in lines[1]

def test_main_e2e_on_decode_error_null():
    # --on-decode-error null: decode エラーのフィールドが None になること
    invalid_name = b'\x81\x07' + b'\x00' * 8
    data  = struct.pack(">I", 1) + "Alice".encode("cp932").ljust(10, b'\x00') + struct.pack(">h", 25)
    data += struct.pack(">I", 2) + invalid_name + struct.pack(">h", 30)
    data += struct.pack(">I", 3) + "Carol".encode("cp932").ljust(10, b'\x00') + struct.pack(">h", 35)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()
    stderr_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "--on-decode-error", "null"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock), \
         patch("sys.stderr", stderr_mock):
        main()

    lines = [line for line in stdout_mock.getvalue().strip().split("\n") if line]
    # 3件全て出力
    assert len(lines) == 3
    assert "Alice" in lines[0]
    # レコード2 の name が None
    assert "'name': None" in lines[1]
    assert "Carol" in lines[2]

def test_main_e2e_on_decode_error_ignore():
    # --on-decode-error ignore: decode 不能バイトが除去されて継続すること
    invalid_name = b'\x81\x07' + b'\x00' * 8
    data  = struct.pack(">I", 1) + "Alice".encode("cp932").ljust(10, b'\x00') + struct.pack(">h", 25)
    data += struct.pack(">I", 2) + invalid_name + struct.pack(">h", 30)
    data += struct.pack(">I", 3) + "Carol".encode("cp932").ljust(10, b'\x00') + struct.pack(">h", 35)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()
    stderr_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age", "--on-decode-error", "ignore"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock), \
         patch("sys.stderr", stderr_mock):
        main()

    lines = [line for line in stdout_mock.getvalue().strip().split("\n") if line]
    # 3件全て出力（エラーなし）
    assert len(lines) == 3
    assert "Alice" in lines[0]
    # レコード2: 0x81は除去され、0x07（chr(7)）が name に残る
    # print(dict) は repr を使うため chr(7) は '\x07' と表示される
    assert repr('\x07') in lines[1]  # repr('\x07') == "'\\x07'"
    assert "Carol" in lines[2]

# --- parse_nibble_set ---

def test_parse_nibble_set_single():
    # 単一値: '0x7' -> frozenset({7})
    assert parse_nibble_set('0x7', '--test') == frozenset({0x7})

def test_parse_nibble_set_multiple():
    # 複数値: '0x7,0xd' -> frozenset({7, 13})
    assert parse_nibble_set('0x7,0xd', '--test') == frozenset({0x7, 0xD})

def test_parse_nibble_set_invalid_hex():
    # 無効な16進数山 0x1g -> SystemExit
    with pytest.raises(SystemExit):
        parse_nibble_set('0x1g', '--test')

def test_parse_nibble_set_out_of_range():
    # 範囲外 0x10 (=16) -> SystemExit
    with pytest.raises(SystemExit):
        parse_nibble_set('0x10', '--test')

def test_decode_bcd_custom_nega_nibble():
    # 0x7 を負符号ニブルとして指定した場合の BCD デコード
    # 0x01 0x23 0x47 -> sign_nibble=0x7 -> 負 -> -1234
    assert decode_bcd(b'\x01\x23\x47', 'tail', frozenset({0x7})) == -1234
    # 0xD は負ニブルでないので正
    assert decode_bcd(b'\x01\x23\x4D', 'tail', frozenset({0x7})) == 1234

def test_decode_zone_custom_nega_nibble():
    # 0x7 を負符号ニブルとして指定した場合の Zone デコード
    # 0xF1 0xF2 0xF3 0x74 -> sign_nibble=(0x74>>4)&0x0F=0x7 -> 負 -> -1234
    assert decode_zone(b'\xF1\xF2\xF3\x74', 'tail', frozenset({0x7})) == -1234
    # 0xD は負ニブルでないので正
    assert decode_zone(b'\xF1\xF2\xF3\xD4', 'tail', frozenset({0x7})) == 1234

def test_main_e2e_bcd_custom_nega_nibble():
    # --bcd-nega-nibble 0x7 指定時、0x7 が負符号になる E2E テスト
    # price: 0x01 0x23 0x47 -> sign_nibble=0x7 -> 負 -> -1234
    price_bcd = b'\x01\x23\x47'
    data = struct.pack(">I3s", 1, price_bcd)

    stdin_mock = MockStdin(data)
    stdout_mock = io.StringIO()

    with patch("sys.argv", ["main.py", ">I3s", "id,price:bcd", "-o", "dict",
                              "--bcd-nega-nibble", "0x7"]), \
         patch("sys.stdin", stdin_mock), \
         patch("sys.stdout", stdout_mock):
        main()

    output = stdout_mock.getvalue()
    assert "'price': -1234" in output
