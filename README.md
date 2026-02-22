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

### オプション

- `-c`, `--condition`: 抽出条件の Python 式 (例: `age > 20`). 指定したフィールド名を変数として使用可能です。
- `-o`, `--output`: 出力形式。`dict` (デフォルト), `json`, `binary` から選択します。
- `-e`, `--encoding`: 文字列 (`bytes`) をデコードする際のエンコーディング。デフォルトは `cp932` です。

### 実行例

テスト用のダミーデータは `create_dummy.py` で生成できます。

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
