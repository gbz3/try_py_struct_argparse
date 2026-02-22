import io
import struct
import sys
from unittest.mock import patch
import pytest

from main import is_safe_expression, validate_args, parse_args, main

def test_is_safe_expression():
    allowed = ["id", "name", "age"]
    # 正常な式
    assert is_safe_expression("age > 20", allowed) is True
    assert is_safe_expression("name == 'Alice' and id % 2 == 0", allowed) is True
    
    # 許可されていない変数
    assert is_safe_expression("unknown > 10", allowed) is False
    
    # 許可されていない構文（関数呼び出し、属性アクセスなど）
    assert is_safe_expression("print(age)", allowed) is False
    assert is_safe_expression("__import__('os').system('ls')", allowed) is False

def test_validate_args_success():
    with patch("sys.argv", ["main.py", ">I10sh", "id,name,age"]):
        args = parse_args()
        st, fields = validate_args(args)
        assert st.format == ">I10sh"
        assert fields == ["id", "name", "age"]

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
