import argparse
import struct
import sys

def encode_bcd(value: int, num_bytes: int, sign_position: str = 'tail') -> bytes:
    """
    整数をパック10進数 (BCD) にエンコードします。
    sign_position:
      'tail' : 最終バイトの下位ニブルが符号 (方式A/COBOL, デフォルト)
      'head' : 先頭バイトの上位ニブルが符号 (方式B)
      'none' : 符号なし (方式C)
    """
    sign = 0xD if value < 0 else 0xC
    digits = list(str(abs(value)))

    if sign_position == 'tail':
        # 数字ニブル数 = num_bytes * 2 - 1 (最終ニブルが符号)
        total_digit_nibbles = num_bytes * 2 - 1
        digits = digits.zfill(total_digit_nibbles) if isinstance(digits, str) else \
                 ['0'] * (total_digit_nibbles - len(digits)) + digits
        nibbles = [int(d) for d in digits] + [sign]
    elif sign_position == 'head':
        # 数字ニブル数 = num_bytes * 2 - 1 (先頭ニブルが符号)
        total_digit_nibbles = num_bytes * 2 - 1
        digits = ['0'] * (total_digit_nibbles - len(digits)) + digits
        nibbles = [sign] + [int(d) for d in digits]
    else:  # 'none'
        total_digit_nibbles = num_bytes * 2
        digits = ['0'] * (total_digit_nibbles - len(digits)) + digits
        nibbles = [int(d) for d in digits]

    result = bytearray()
    for i in range(0, len(nibbles), 2):
        result.append((nibbles[i] << 4) | nibbles[i + 1])
    return bytes(result)

def create_normal_data():
    """フォーマット: >I10sh (id, name, age)"""
    fmt = '>I10sh'
    records = [
        (1, "Alice".encode('cp932'), 25),
        (2, "Bob".encode('cp932'), 30),
        (3, "Charlie".encode('cp932'), 18),
        (4, "太郎".encode('cp932'), 40),
    ]
    for r in records:
        sys.stdout.buffer.write(struct.pack(fmt, r[0], r[1], r[2]))

def encode_zone(value: int, num_bytes: int, sign_position: str = 'tail') -> bytes:
    """
    整数をゾーン10進数にエンコードします。
    各バイトの下位ニブル = 数字、上位ニブル = ゾーン(0xF) or 符号。
    sign_position:
      'tail' : 最終バイトの上位ニブルが符号 (COBOL/EBCDIC デフォルト)
      'head' : 先頭バイトの上位ニブルが符号
      'none' : 符号なし (全バイト上位ニブルはゾーン)
    """
    sign = 0xD if value < 0 else 0xC
    zone = 0xF
    digits = list(str(abs(value)).zfill(num_bytes))
    result = bytearray()
    for i, d in enumerate(digits):
        digit = int(d)
        if sign_position == 'tail' and i == len(digits) - 1:
            result.append((sign << 4) | digit)
        elif sign_position == 'head' and i == 0:
            result.append((sign << 4) | digit)
        else:
            result.append((zone << 4) | digit)
    return bytes(result)

def create_zone_data():
    """フォーマット: >I4sh (id, amount:zone, age)  ›amount は4バイトゾーン10進(tail方式)"""
    fmt = '>I4sh'
    records = [
        (1,  1234, 25),
        (2, -5678, 30),
        (3,   100, 18),
        (4,  9999, 40),
    ]
    for rec_id, amount, age in records:
        zone_amount = encode_zone(amount, 4, 'tail')
        sys.stdout.buffer.write(struct.pack(fmt, rec_id, zone_amount, age))

def create_bcd_data():
    """フォーマット: >I3sh (id, price:bcd, age)  ※price は3バイトBCD(tail方式)"""
    fmt = '>I3sh'
    records = [
        (1, 12345, 25),
        (2, -6789, 30),
        (3, 100,   18),
        (4, 99999, 40),
    ]
    for rec_id, price, age in records:
        bcd_price = encode_bcd(price, 3, 'tail')
        sys.stdout.buffer.write(struct.pack(fmt, rec_id, bcd_price, age))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="テスト用ダミーバイナリデータを標準出力に書き出します。")
    parser.add_argument(
        "--mode",
        choices=["normal", "bcd", "zone"],
        default="normal",
        help="出力するデータの種類: normal='>I10sh'(id,name,age), bcd='>I3sh'(id,price:bcd,age), zone='>I4sh'(id,amount:zone,age) (デフォルト: normal)"
    )
    args = parser.parse_args()

    if args.mode == "bcd":
        create_bcd_data()
    elif args.mode == "zone":
        create_zone_data()
    else:
        create_normal_data()
