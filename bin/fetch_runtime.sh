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

echo "    查询 Release: $API"
meta="$(curl -sS -m 20 "$API" 2>/dev/null)"
tag="$(printf '%s' "$meta" | tr ',' '\n' | grep -o '"tag_name":"[^"]*"' | head -1 | cut -d'"' -f4)"
if [ -z "$tag" ]; then
  echo "    无法读取 Release 信息（网络受限？），请手动下载 $ASSET 解压到 $S/"
  exit 1
fi
assets="$(curl -sS -m 20 "https://api.github.com/repos/$REPO/releases/tags/$tag" 2>/dev/null)"
aid="$(printf '%s' "$assets" | tr '{' '\n' | grep -F "\"name\":\"$ASSET\"" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)"
if [ -z "$aid" ]; then
  echo "    Release $tag 里找不到 $ASSET，请检查仓库 Release 页面"
  exit 1
fi
echo "    下载 asset #$aid ($tag) ..."
tmp="$S/.runtime.tar.gz.part"
if curl -sSL -m 600 -H 'Accept: application/octet-stream' \
     -o "$tmp" "https://api.github.com/repos/$REPO/releases/assets/$aid"; then
  mv "$tmp" "$S/runtime.tar.gz"
  tar -xzf "$S/runtime.tar.gz" -C "$S" && rm -f "$S/runtime.tar.gz"
  chmod +x "$S/.runtime/bin/"* 2>/dev/null || true
  echo "    运行时就绪：$S/.runtime"
  [ -x "$S/.runtime/bin/php" ] && [ -x "$S/.runtime/bin/mysqld" ]
else
  rm -f "$tmp"
  echo "    下载失败"
  exit 1
fi
