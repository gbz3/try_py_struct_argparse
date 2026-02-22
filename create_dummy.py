import struct
import sys

def create_dummy_data():
    # フォーマット: >I10sh (ビッグエンディアン, 4バイト符号なし整数, 10バイト文字列, 2バイト符号あり短整数)
    # 合計サイズ: 4 + 10 + 2 = 16バイト
    fmt = '>I10sh'
    
    records = [
        (1, "Alice".encode('cp932'), 25),
        (2, "Bob".encode('cp932'), 30),
        (3, "Charlie".encode('cp932'), 18),
        (4, "太郎".encode('cp932'), 40), # 日本語テスト
    ]
    
    for r in records:
        sys.stdout.buffer.write(struct.pack(fmt, r[0], r[1], r[2]))

if __name__ == "__main__":
    create_dummy_data()
