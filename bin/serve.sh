#!/bin/sh
# 启动站点：优先用仓库自带自包含运行时，否则回退到系统 PHP
S="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$S/.runtime/bin/php" ]; then
  PHP="$S/.runtime/bin/php"; PHPINI="-c $S/.runtime/php.ini"
  export LD_LIBRARY_PATH="$S/.runtime/lib:${LD_LIBRARY_PATH:-}"
else
  PHP=php; PHPINI=""
fi
export PHP_CLI_SERVER_WORKERS="${PHP_CLI_SERVER_WORKERS:-8}"
HOST="${HOST:-0.0.0.0}"; PORT="${PORT:-8080}"
echo "LinkAI PHP 站点: http://$HOST:$PORT  (workers=$PHP_CLI_SERVER_WORKERS)"
exec "$PHP" $PHPINI -S "$HOST:$PORT" -t "$S/public" "$S/public/index.php"
