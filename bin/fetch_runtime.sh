#!/bin/sh
# 从 GitHub Release 拉取自包含 PHP/MySQL 运行时（仓库本身不携带二进制）
# 用法：sh bin/fetch_runtime.sh
S="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${LK_REPO:-Lisir2002/Mini_LinkAI}"
ASSET="${LK_RUNTIME_ASSET:-runtime.tar.gz}"
API="https://api.github.com/repos/$REPO/releases/latest"

if [ -x "$S/.runtime/bin/php" ] && [ -x "$S/.runtime/bin/mysqld" ]; then
  echo "    运行时已存在，跳过"
  exit 0
fi

echo "    查询 Release 附件"
meta="$(curl -sS -m 20 -H 'Accept: application/vnd.github+json' "$API" 2>/dev/null)"
tag=""; aid=""
if command -v python3 >/dev/null 2>&1; then
  pair="$(printf '%s' "$meta" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    name = "'"$ASSET"'"
    for a in d.get("assets", []):
        if a.get("name") == name:
            print(a["id"], d.get("tag_name", "")); break
except Exception:
    pass' 2>/dev/null)"
  aid="$(printf '%s' "$pair" | awk '{print $1}')"
  tag="$(printf '%s' "$pair" | awk '{print $2}')"
fi
if [ -z "$aid" ]; then
  echo "    无法解析 Release 附件（需要 python3，或网络受限）"
  echo "    请手动下载 $ASSET 并解压到 $S/"
  exit 1
fi
echo "    asset #$aid (tag $tag)"

tmp="$S/.runtime.tar.gz.part"
ok=0
# 通道 1：GitHub API asset 端点（会 302 到 release-assets.githubusercontent.com）
if curl -sSL -m 900 -H 'Accept: application/octet-stream' \
     -o "$tmp" "https://api.github.com/repos/$REPO/releases/assets/$aid" \
   && [ -s "$tmp" ] && [ "$(wc -c < "$tmp")" -gt 1000000 ]; then
  ok=1
else
  rm -f "$tmp"
  # 通道 2：github.com Release 直链（部分网络环境下更通）
  echo "    通道 1 失败，改用 Release 直链"
  if curl -sSL -m 900 -o "$tmp" \
       "https://github.com/$REPO/releases/download/$tag/$ASSET" \
     && [ -s "$tmp" ] && [ "$(wc -c < "$tmp")" -gt 1000000 ]; then
    ok=1
  fi
fi
if [ "$ok" -ne 1 ]; then
  rm -f "$tmp"
  echo "    下载失败：请手动下载 $ASSET 解压到 $S/，或改用 README 中的方式 B（系统 PHP + MySQL）"
  exit 1
fi
mv "$tmp" "$S/runtime.tar.gz"
tar -xzf "$S/runtime.tar.gz" -C "$S" && rm -f "$S/runtime.tar.gz"
chmod +x "$S/.runtime/bin/"* 2>/dev/null || true
echo "    运行时就绪：$S/.runtime"
[ -x "$S/.runtime/bin/php" ] && [ -x "$S/.runtime/bin/mysqld" ]
