# try_py_struct_argparse

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
