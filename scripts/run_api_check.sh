#!/bin/sh
# 全量 API 实测：重置演示库 → 迁移 → 拉起 mock 上游 + uvicorn → 逐接口实测 → 报告
set -e
cd /root/userdata/workspace/ai-chatroom
# 清理历史孤儿进程（崩溃残留会占用端口，导致实测打到旧代码）
for pid in $(ps aux | grep "[u]vicorn app.main" | awk '{print $2}'); do kill "$pid" 2>/dev/null || true; done
for pid in $(ps aux | grep "[d]ev_mock_upstream" | awk '{print $2}'); do kill "$pid" 2>/dev/null || true; done
for pid in $(ps aux | grep "[v]ite.js preview" | awk '{print $2}'); do kill "$pid" 2>/dev/null || true; done
sleep 1
redis-cli -a spikepass -n 0 flushdb >/dev/null 2>&1 || true
pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 || pg_ctlcluster 16 main start
redis-cli -a spikepass ping >/dev/null 2>&1 || redis-server --daemonize yes --port 6379 --requirepass spikepass --save ''
export DATABASE_URL="postgresql+asyncpg://aicr:spikepass@127.0.0.1:5432/ai_chatroom_dev"
export REDIS_URL="redis://:spikepass@127.0.0.1:6379/0"
export JWT_SECRET="dev-secret-for-local-e2e-0123456789abcdef"
export ENVIRONMENT=development
export FEATURE_FILE_UPLOAD=true
export UPLOAD_DIR=$PWD/var/uploads
export PYTHONPATH=$PWD/backend
if [ ! -f /tmp/dev_cipher.key ]; then
  /tmp/aicr-venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > /tmp/dev_cipher.key
fi
CHANNEL_CIPHER_KEY=$(cat /tmp/dev_cipher.key); export CHANNEL_CIPHER_KEY
cleanup() { kill $MOCK $API $WEB 2>/dev/null || true; }
trap cleanup EXIT
cd backend
/tmp/aicr-venv/bin/alembic upgrade head
/tmp/aicr-venv/bin/python ../scripts/e2e_reset.py
cd ..
/tmp/aicr-venv/bin/python scripts/dev_mock_upstream.py > /tmp/mock.log 2>&1 &
MOCK=$!
cd backend
/tmp/aicr-venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/api.log 2>&1 &
API=$!
cd ..
sleep 5
/tmp/aicr-venv/bin/python scripts/api_full_check.py
RC=$?
kill $MOCK $API 2>/dev/null || true
echo "API_CHECK_EXIT=$RC"
