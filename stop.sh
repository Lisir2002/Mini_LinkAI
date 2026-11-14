#!/bin/sh
# 停止站点（保留数据库数据）
S="$(cd "$(dirname "$0")" && pwd)"
for p in $(ps -eo pid,cmd | grep -E "$S/public/index.php|$S/.runtime/bin/mysqld" | grep -v grep | awk '{print $1}'); do
  kill "$p" 2>/dev/null || true
done
rm -f /tmp/linkai-mysql.sock /tmp/linkai-mysqld.pid
echo "已停止（数据在 $S/.db/data 保留）"
