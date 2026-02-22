import io
import struct
from unittest.mock import patch
import pytest

from main import is_safe_expression, validate_args, parse_args, main, decode_bcd, parse_field_specs, get_format_type_codes

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
        assert field_specs == [("id", None), ("name", None), ("age", None)]

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
    assert parse_field_specs("id,name,age") == [("id", None), ("name", None), ("age", None)]

def test_parse_field_specs_with_bcd():
    assert parse_field_specs("id,price:bcd,name") == [("id", None), ("price", "bcd"), ("name", None)]

# --- decode_bcd ---

def test_decode_bcd_tail_positive():
    # 0x01 0x23 0x4C -> +1234
    assert decode_bcd(b'\x01\x23\x4C', 'tail') == 1234

def test_decode_bcd_tail_negative():
    # 0x01 0x23 0x4D -> -1234
    assert decode_bcd(b'\x01\x23\x4D', 'tail') == -1234

def test_decode_bcd_tail_unsigned():
    # 0x01 0x23 0x4F -> +1234 (F=符号なし)
    assert decode_bcd(b'\x01\x23\x4F', 'tail') == 1234

def test_decode_bcd_head_positive():
    # 0xC0 0x12 0x34 -> +1234 (sign=C, digits=[0,1,2,3,4] -> '01234' -> 1234)
    # head: 3バイト = 1符号ニブル + 5桁ニブル
    assert decode_bcd(b'\xC0\x12\x34', 'head') == 1234

def test_decode_bcd_head_negative():
    # 0xD0 0x05 0x67 -> -567
    assert decode_bcd(b'\xD0\x05\x67', 'head') == -567

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
