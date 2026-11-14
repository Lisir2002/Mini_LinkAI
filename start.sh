#!/bin/sh
# Mini_LinkAI PHP 版 · 无容器一键启动（幂等）
# 用法：sh start.sh   然后访问 http://127.0.0.1:8080
S="$(cd "$(dirname "$0")" && pwd)"
LD="$S/.runtime/lib"
PHP="$S/.runtime/bin/php"
PHPINI="-c $S/.runtime/php.ini"
MYSQLD="$S/.runtime/bin/mysqld"
SOCK=/tmp/linkai-mysql.sock
PORT="${PORT:-8080}"
export LD_LIBRARY_PATH="$LD:${LD_LIBRARY_PATH:-}"

# 仓库不携带二进制运行时（放 GitHub Release），首次启动自动拉取
if [ ! -x "$PHP" ] && [ -f "$S/bin/fetch_runtime.sh" ]; then
  echo "== [0/4] 首次运行：拉取自包含 PHP/MySQL 运行时 =="
  sh "$S/bin/fetch_runtime.sh" || echo "    拉取失败，将回退到系统 PHP/MySQL（见 README 方式 B）"
fi

# 回退：没带自包含运行时就用系统 PHP（phpStudy / 宝塔 / XAMPP 场景）
[ -x "$PHP" ] || PHP=php
[ -f "$S/.runtime/php.ini" ] || PHPINI=""

mysql_up() {
  "$PHP" $PHPINI -r '$p=new PDO("mysql:unix_socket=/tmp/linkai-mysql.sock","root","");$p->query("SELECT 1");' >/dev/null 2>&1
}

web_up() { curl -sS -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null; }

echo "== [1/4] MySQL (原生，无容器) =="
if mysql_up; then
  echo "    MySQL 已在运行（socket $SOCK）"
elif [ -x "$MYSQLD" ]; then
  if [ ! -f "$S/.db/data/ibdata1" ]; then
    echo "    首次初始化数据目录（约 1~2 分钟）…"
    rm -rf "$S/.db/data" && mkdir -p "$S/.db/data"
    "$MYSQLD" --no-defaults --initialize-insecure --user=root --datadir="$S/.db/data" \
      --secure-file-priv="$S/data" --ssl=0 --skip-log-bin --log-error="$S/logs/mysql-init.log" >/dev/null 2>&1
  fi
  ( "$MYSQLD" --no-defaults --user=root --datadir="$S/.db/data" \
      --socket="$SOCK" --pid-file=/tmp/linkai-mysqld.pid --log-error="$S/logs/mysqld.log" \
      --port="${DB_PORT:-3308}" --bind-address=127.0.0.1 --ssl=0 --skip-log-bin --mysqlx=0 \
      --max_connections=100 --secure-file-priv="$S/data" \
      --innodb_flush_method=nosync --innodb_flush_log_at_trx_commit=0 --innodb_doublewrite=0 \
      --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci \
      --default-time-zone='+00:00' >/dev/null 2>&1 ) &
  i=0; until mysql_up; do i=$((i+1)); [ "$i" -gt 40 ] && { echo "    MySQL 启动失败，看 $S/logs/mysqld.log"; exit 1; }; sleep 1; done
  echo "    MySQL 已启动（约 ${i}s）"
else
  echo "    未找到 mysqld，请把 DB_HOST/DB_PORT/DB_USER/DB_PASS 写进 .env.php 指向外部 MySQL"
fi

echo "== [2/4] 建库 / 建表 / 种子数据 =="
if [ -x "$S/.runtime/bin/php" ]; then
  "$PHP" $PHPINI "$S/bin/create_db.php" 2>&1 | sed 's/^/    /'
  "$PHP" $PHPINI "$S/bin/migrate.php" 2>&1 | sed 's/^/    /'
else
  echo "    使用外部数据库时请手动导入 src/schema.sql 并执行 bin/migrate.php"
fi

echo "== [3/4] PHP 内置服务器 =="
# SSE 长连接会占用 worker；8 个在压测时容易被占满，默认给 16
export PHP_CLI_SERVER_WORKERS="${PHP_CLI_SERVER_WORKERS:-16}"
if web_up; then
  echo "    Web 已在运行"
else
  ( exec "$PHP" $PHPINI -S "0.0.0.0:$PORT" -t "$S/public" "$S/public/index.php" \
      > "$S/logs/serve.log" 2>&1 ) &
  i=0; until web_up; do i=$((i+1)); [ "$i" -gt 20 ] && { echo "    Web 启动失败"; exit 1; }; sleep 1; done
  echo "    Web 已启动（workers=$PHP_CLI_SERVER_WORKERS）"
fi

echo "== [4/4] 就绪 =="
curl -sS -m 5 "http://127.0.0.1:$PORT/api/health"; echo
echo "    站点: http://127.0.0.1:$PORT"
echo "    管理员: admin@demo.com / AdminPass2026（首次登录强制改密）"
echo "    停止: sh stop.sh"
