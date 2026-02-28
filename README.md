# try_py_struct_argparse

固定長レコードのバイナリファイルを標準入力から読み込み、指定したフォーマットでアンパックして出力する Python CLI ツールです。

## 概要

- `struct` モジュールの書式文字列を使用してバイナリデータを解析します。
- アンパックした各フィールドに名前を付け、Python の式を用いた柔軟な抽出条件（フィルタリング）が可能です。
- 出力形式は `dict` (Python の辞書表現), `json` (JSON Lines), `binary` (バイナリそのまま) から選択できます。
- AST (抽象構文木) を用いた抽出条件の安全性チェックを実装しており、不正なコードの実行を防ぎます。
- `multiprocessing.Pool` を用いたマルチコア並列処理に対応しており、巨大な入力データを効率よく処理できます。

## 動作要件

- Python **3.8** 以上

## 使い方

```bash
cat input.bin | python3 main.py <format> <fields> [options]
```

### 引数

- `format` (必須): `struct` モジュールの書式文字列 (例: `>I10sh`)
- `fields` (必須): アンパックした各フィールド名 (カンマ区切り, 例: `id,name,age`)
  - `フィールド名:bcd` と指定するとそのフィールドをパック10進数 (BCD) としてデコードします (例: `id,price:bcd,age`)
  - `フィールド名:bcd:符号位置` と指定するとフィールド単位で符号位置を上書きできます (例: `id,price:bcd:tail,discount:bcd:head`)
  - `フィールド名:zone` と指定するとそのフィールドをゾーン10進数としてデコードします (例: `id,amount:zone,age`)
  - `フィールド名:zone:符号位置` と指定するとフィールド単位で符号位置を上書きできます (例: `id,amount:zone:tail`)
  - 符号位置を省略した場合は `--bcd-sign` / `--zone-sign` のグローバル設定が使用されます

### オプション

- `-c`, `--condition`: 抽出条件の Python 式 (例: `age > 20`). 指定したフィールド名を変数として使用可能です。
- `-o`, `--output`: 出力形式。`dict` (デフォルト), `json`, `binary` から選択します。
- `-e`, `--encoding`: 文字列 (`bytes`) をデコードする際のエンコーディング。デフォルトは `cp932` です。
- `--bcd-sign`: BCD フィールドの符号の位置。以下から選択します（デフォルト: `tail`）。
  - `tail`: 最終バイトの下位ニブルが符号 (COBOL/汎用機方式)
  - `head`: 先頭バイトの上位ニブルが符号
  - `none`: 符号なし（全ニブルが数字）
- `--zone-sign`: ゾーン10進フィールドの符号の位置。以下から選択します（デフォルト: `tail`）。
  - `tail`: 最終バイトの上位ニブルが符号 (COBOL/EBCDIC 方式)
  - `head`: 先頭バイトの上位ニブルが符号
  - `none`: 符号なし（全バイト上位ニブルはゾーン）
- `-n`, `--max-records`: 出力レコードの最大件数 (`N`)。N 件に達した時点で処理を中止します。省略時は無制限です。`--condition` と組み合わせた場合、条件を通過した件数が上限の基準になります。
- `--record-num`: 出力レコードの先頭に入力レコード番号フィールド `_rec_no`（1始まり）を付与します。`-o binary` の場合は無効です。なお、`--condition` 内では本フラグの指定有無に関わらず `_rec_no` を常に参照できます。`--condition` でスキップされたレコードも番号にカウントされるため、`_rec_no` は常に入力ファイル内の位置を示します。
- `--on-decode-error`: 文字列フィールドのデコードエラー発生時の動作を指定します（デフォルト: `abort`）。
  - `abort`: 即時中止します（デフォルト）。
  - `skip`: エラーが発生したレコードをスキップして処理を継続します。エラー内容は stderr に警告として出力されます。
  - `null`: エラーが発生したフィールドを `None` にして処理を継続します。エラー内容は stderr に警告として出力されます。
  - `ignore`: デコード不能なバイトを除去した文字列として処理を継続します（`errors="ignore"` と同等）。警告は出力されません。
  - **注意**: `:bcd` / `:zone` フィールドは対象外です（BCD/Zone は算術変換のため UnicodeDecodeError が発生しません）。
- `--bcd-nega-nibble`: BCD フィールドの負符号とみなすニブル値を、カンマ区切りの16進数で指定します（デフォルト: `0x7`）。
  - 例: `0xd`（0xD 単独）、`0x7,0xd`（0x7 と 0xD の両方を負符号とみなす）
  - 指定したニブル値に一致した場合は負、それ以外はすべて正とみなします。
  - 値は 0x0〜0xf の範囲で指定してください。範囲外はエラーになります。
- `--zone-nega-nibble`: Zone 10進フィールドの負符号とみなすニブル値を、カンマ区切りの16進数で指定します（デフォルト: `0x7`）。書式は `--bcd-nega-nibble` と同様です。

### 実行例

テスト用のダミーデータは `create_dummy.py` で生成できます。

| `--mode` | フォーマット | フィールド |
|---|---|---|
| `normal` (デフォルト) | `>I10sh` | id, name, age |
| `bcd` | `>I3sh` | id, price:bcd, age |
| `zone` | `>I4sh` | id, amount:zone, age |

**1. 基本的な使い方 (dict 形式で出力)**
```bash
python3 create_dummy.py | python3 main.py ">I10sh" "id,name,age"
```

**2. 抽出条件を指定して JSON Lines 形式で出力**
```bash
python3 create_dummy.py | python3 main.py ">I10sh" "id,name,age" -c "age > 20" -o json
```

**3. 抽出条件に合致するレコードをバイナリのまま出力**
```bash
python3 create_dummy.py | python3 main.py ">I10sh" "id,name,age" -c "name == '太郎'" -o binary > output.bin
```

**4. BCD フィールドを含むレコードの出力**
```bash
python3 create_dummy.py --mode bcd | python3 main.py ">I3sh" "id,price:bcd,age"
```

**5. BCD フィールドに対する抽出条件（負数も指定可能）**
```bash
python3 create_dummy.py --mode bcd | python3 main.py ">I3sh" "id,price:bcd,age" -c "price > -1000"
```

**6. フィールド毎に符号位置を指定（BCD）**
```bash
# price は tail 方式、discount は head 方式で個別にデコード
python3 main.py ">I3s3s" "id,price:bcd:tail,discount:bcd:head" < input.bin
```

**7. ゾーン10進フィールドを含むレコードの出力**
```bash
python3 create_dummy.py --mode zone | python3 main.py ">I4sh" "id,amount:zone,age"
```

**7. ゾーン10進フィールドに対する抽出条件**
```bash
python3 create_dummy.py --mode zone | python3 main.py ">I4sh" "id,amount:zone,age" -c "amount > 0" -o json
```

**8. 出力レコード件数を最大 2 件に制限**
```bash
python3 create_dummy.py | python3 main.py ">I10sh" "id,name,age" -n 2
```

**9. 抽出条件と最大件数の組み合わせ（条件通過後 1 件で終了）**
```bash
python3 create_dummy.py | python3 main.py ">I10sh" "id,name,age" -c "age > 20" -n 1
```

**10. 入力レコード番号を先頭フィールドに付与して出力**
```bash
python3 create_dummy.py | python3 main.py ">I10sh" "id,name,age" --record-num
```

**11. 入力レコード番号でフィルタリング（2番目のレコードのみ出力）**
```bash
python3 create_dummy.py | python3 main.py ">I10sh" "id,name,age" -c "_rec_no == 2" -o json
```

**12. 入力レコード番号フィルタリングに最大件数制限を組み合わせ**
```bash
# 3番目以降のレコードを最大2件出力
python3 create_dummy.py | python3 main.py ">I10sh" "id,name,age" -c "_rec_no >= 3" -n 2 --record-num
```

**13. デコードエラーのあるレコードをスキップして処理を継続**
```bash
# UnicodeDecodeError が発生したレコードを除外し、残りのレコードを出力する
cat input.bin | python3 main.py ">I10sh" "id,name,age" --on-decode-error skip
```

**14. デコードエラーのあるフィールドを None にして処理を継続**
```bash
# エラーフィールドを None にして全レコードを出力する
cat input.bin | python3 main.py ">I10sh" "id,name,age" --on-decode-error null -o json
```

**15. デコード不能バイトを除去して処理を継続**
```bash
# 不正バイトを無音で除去し、文字列として継続処理する
cat input.bin | python3 main.py ">I10sh" "id,name,age" --on-decode-error ignore
```

**16. BCD 負符号ニブル値を変更（COBOL/汎用機の 0xD を負とみなす）**
```bash
# デフォルト(0x7)から COBOL 方式(0xD)へ変更
python3 create_dummy.py --mode bcd | python3 main.py ">I3sh" "id,price:bcd,age" --bcd-nega-nibble 0xd
```

**17. 複数のニブル値を負符号として指定**
```bash
# 0x7 と 0xD のどちらも負符号とみなす
cat input.bin | python3 main.py ">I3s" "id,price:bcd" --bcd-nega-nibble 0x7,0xd
```

**18. Zone フィールドの負符号ニブル値を変更**
```bash
# Zone フィールドの負符号を COBOL 方式(0xD)に変更
python3 create_dummy.py --mode zone | python3 main.py ">I4sh" "id,amount:zone,age" --zone-nega-nibble 0xd
```

## 内部処理の最適化について

巨大な入力データを効率よく処理するため、以下の最適化を実施しています。CLI の引数・使い方は変わりません。

### マルチコア並列処理 (`multiprocessing.Pool`)

- 入力ストリームを `BATCH_SIZE`（デフォルト: 256）レコード単位で読み込み、`multiprocessing.Pool.imap()` で複数のワーカープロセスに分散処理します。
- 使用するワーカー数は `os.cpu_count()` に自動設定され、利用可能なすべての CPU コアを活用します。
- **メインプロセス**: stdin の読み込みと stdout への書き込みのみ担当します。
- **ワーカープロセス**: struct アンパック・BCD/Zone デコード・抽出条件評価（eval）を担当します。
- `pool.imap()` により出力順序は入力順序と一致することが保証されます（`_rec_no` の整合性を維持）。
- `--max-records` に達した時点で `pool.terminate()` により早期終了します。

### ワーカー初期化の効率化

- `struct.Struct` のコンパイルと条件式の `compile()` はワーカー起動時に **1 回だけ** 実行されます（`_worker_init()` 関数）。バッチごとに繰り返さないため、オーバーヘッドを削減します。

### BCD / Zone デコードの整数演算最適化

- 従来実装（`int(''.join(str(n) for n in nibbles))`）のリスト生成・文字列結合・int 変換の 3 ステップを、`value = value * 10 + nibble` の単純な整数演算ループに置き換えました。全レコード・全 BCD/Zone フィールドで効きます。

### 出力のバッファリング

- dict/json 出力: バッチ内の行を `'\n'.join(lines)` でまとめて `sys.stdout.write()` を 1 回呼び出します。
- binary 出力: `sys.stdout.buffer.write(b''.join(chunks))` でバッチ単位に一括書き込みします。
- いずれも `print()` / `write()` の呼び出し回数（システムコール数）を大幅に削減します。

### チューニング

`main.py` 冒頭の `BATCH_SIZE` 定数でバッチあたりのレコード数を変更できます。

```python
BATCH_SIZE = 256  # 大きいほど I/O 効率が上がるが、メモリ使用量も増える
```

## テストの実行

`pytest` を使用して自動テストを実行できます。

```bash
python3 -m pip install pytest
python3 -m pytest test_main.py -v
```

---

## 開発環境 (VS Code 拡張機能)

このリポジトリでは、快適な Python CLI 開発のために以下の VS Code 拡張機能を推奨・自動インストールする設定 (`.vscode/extensions.json`, `.devcontainer/devcontainer.json`) を含んでいます。

- **Python (`ms-python.python`)**: Python の基本サポート（デバッグ、テスト実行など）を提供します。
- **Pylance (`ms-python.vscode-pylance`)**: 高速で強力な型チェックとコード補完 (IntelliSense) を提供します。
- **Ruff (`charliermarsh.ruff`)**: 非常に高速な Python 用のリンターおよびフォーマッターです。コードの品質を保ちます。

## Git LFS について

このリポジトリでは巨大なバイナリファイル等を扱わないため、Git LFS は不要です。
環境によっては `git-lfs` 関連の警告が出ることがあるため、以下のコマンドで Git LFS のフックを削除しています。

```bash
rm -f .git/hooks/post-commit .git/hooks/post-checkout .git/hooks/post-merge .git/hooks/pre-push
```
