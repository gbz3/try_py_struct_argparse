#!/usr/bin/bash

load_layout() {
  local file="$1"

  if [[ ! -f "$file" ]]; then
    echo "file '$file' not found." >&2
    return 1
  fi

  # IFS を一時的に '|' （または改行）に設定して read で分解
  # -r はバックスラッシュをそのまま使うオプション
  while IFS='|' read -r key value || [[ -n "$key" ]]; do
    # 空行やコメント行をスキップ
    [[ -z "$key" || "$key" =~ ^# ]] && continue

    # キー名に含まれる「-」「.」をアンダースコアに変換
    local safe_key="conf_${key//[-.]/_}"

    # printf -v を使って安全に代入（eval を避ける）
    printf -v "$safe_key" "%s" "$value"
  done < "$file"
}

get_conf() {
  local target="conf_${1//[-.]/_}"
  # 関節参照で値を返す
  echo "${!target}"
}

load_layout layouts.txt

echo "[$(get_conf 'fmt-01')]"
echo "[$(get_conf 'fld-01')]"
echo "[$(get_conf 'fmt-02')]"
echo "[$(get_conf 'fld-02')]"

