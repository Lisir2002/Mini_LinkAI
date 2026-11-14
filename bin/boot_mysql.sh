#!/bin/sh
# 全自包含 MySQL 启动（二进制与动态库均在 .runtime/，不依赖系统包）
S=/data/workspace/linkai-site
export LD_LIBRARY_PATH="$S/.runtime/lib"
M="$S/.runtime/bin/mysqld"
PHP="$S/.runtime/bin/php"
PHPINI="$S/.runtime/php.ini"
DATADIR="$S/.db/data"
SOCK="$S/run/mysql.sock"
LOG="$S/logs"

: > "$LOG/boot.log"
echo "boot start $(date)" >> "$LOG/boot.log"

if [ ! -f "$DATADIR/ibdata1" ]; then
  echo "initializing datadir..." >> "$LOG/boot.log"
  "$M" --no-defaults --initialize-insecure --user=root --datadir="$DATADIR" --ssl=0 \
       --log-error="$LOG/mysql-init.log" > "$LOG/mysql-init.out" 2>&1
  echo "init rc=$?" >> "$LOG/boot.log"
fi

echo "starting mysqld..." >> "$LOG/boot.log"
"$M" --no-defaults --user=root --datadir="$DATADIR" \
     --socket="$SOCK" --pid-file="$S/run/mysqld.pid" \
     --log-error="$LOG/mysqld.log" --port=3308 --bind-address=127.0.0.1 \
     --ssl=0 --skip-log-bin --max_connections=100 \
     --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci \
     --default-time-zone='+00:00' > "$LOG/mysqld.out" 2>&1 &
echo "mysqld_pid=$!" >> "$LOG/boot.log"

i=0
while [ "$i" -lt 90 ]; do
  if "$PHP" -c "$PHPINI" "$S/bin/create_db.php" >> "$LOG/boot.log" 2>&1; then
    echo "db ready after ${i}s" >> "$LOG/boot.log"
    exit 0
  fi
  i=$((i+1))
  sleep 1
done
echo "DB_FAILED" >> "$LOG/boot.log"
exit 1
