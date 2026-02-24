# try_py_struct_argparse

固定長レコードのバイナリファイルを標準入力から読み込み、指定したフォーマットでアンパックして出力する Python CLI ツールです。

## 概要

- `struct` モジュールの書式文字列を使用してバイナリデータを解析します。
- アンパックした各フィールドに名前を付け、Python の式を用いた柔軟な抽出条件（フィルタリング）が可能です。
- 出力形式は `dict` (Python の辞書表現), `json` (JSON Lines), `binary` (バイナリそのまま) から選択できます。
- AST (抽象構文木) を用いた抽出条件の安全性チェックを実装しており、不正なコードの実行を防ぎます。

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
