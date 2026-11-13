# LinkAI

多房间 AI 聊天平台：管理员按**协议**接入模型渠道，成员用邀请码注册后单聊 AI，或进房间与其他人和 AI 一起讨论。

## 已实现

**成员端（移动优先）**：登录/注册（邮箱或手机号 + 邀请码）、首次强制改密、会话列表（搜索/置顶/删除撤销）、
SSE 流式对话（打字机效果、停止生成、用量显示、模型切换）、房间广场（创建/加入/搜索）、
房间群聊（@AI 触发、成员昵称、3 秒增量轮询）、我的页（用量进度、主题切换、管理入口）。

**管理端（移动卡片 + 桌面双栏）**：渠道 CRUD（**先选协议 → 表单动态渲染 → 厂商预设一键填充**、
参数白名单、优先级权重、连通性测试、同步上游模型、启停与最后渠道保护、删除影响范围二次确认）、
模型注册表（对外名与上游解耦、绑定渠道、设默认、乐观锁）、邀请码（批量生成、掩码列表、作废）、
系统设置（配额、注册方式、内容安全、特性开关、保留天数）。

**后端**：FastAPI + PostgreSQL 16 + Redis 7；三协议适配器（OpenAI 兼容 / Anthropic / Gemini）；
渠道选路（优先级 + 权重 + 冷却跳过 + 鉴权失败立即禁用 + 连续失败自动禁用）；
配额原子预扣与结算退回（首次插入分支同样受限）；会话级串行与 generation 防覆盖；
JWT + 黑名单 + 改密吊销其他 token；argon2id；渠道 Key Fernet 加密只回显末 4 位；
审计日志；APScheduler 悬挂兜底与渠道健康巡检。

## 图标系统

全部图标为**自绘内联 SVG**，不依赖任何图标字体或第三方图标库：

- `frontend/src/icons/index.ts` —— 53 枚图标，按功能语义手工设计路径；统一 24×24 网格、
  1.7 描边、圆头圆角连接，实心仅用于点睛（机器人眼睛、停止块、主题半圆等）
- `frontend/src/components/common/AppIcon.vue` —— 唯一渲染入口，`currentColor` 继承场景语义色，
  `size` 控制尺寸，传 `title` 时输出无障碍名称、否则 `aria-hidden`
- 图形以结构化 shape 数组声明（path/circle/rect/line/polyline/polygon），不使用 `v-html`
- `LEGACY_MAP` 保留旧名映射，`resolveIcon` 对未知名回退到警示图标而不是渲染空白
- 预览全部图标：`cd frontend && node tools/icon-gallery.mjs`，产物见 `docs/screenshots/自绘图标总览.png`
- 测试覆盖：图标库完整性、旧名映射、未知回退、无障碍属性，以及**源码扫描断言工程内不再残留任何图标字体用法**

## 本地跑起来（无需真实模型 Key）

```bash
# 1. 依赖服务
docker compose -f deploy/docker-compose.dev.yml up -d      # 或本机自装 PostgreSQL + Redis

# 2. 后端
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://ai_chatroom:devpassword@127.0.0.1:5432/ai_chatroom
export REDIS_URL=redis://:devpassword@127.0.0.1:6379/0
export JWT_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")
export CHANNEL_CIPHER_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
alembic upgrade head
SEED_ADMIN_EMAIL=admin@demo.com SEED_ADMIN_PASSWORD=AdminPass2026 python -m scripts.seed
uvicorn app.main:app --reload --port 8000

# 3. 本地 mock 上游（OpenAI 兼容，用于无 Key 时验证全链路）
python scripts/dev_mock_upstream.py            # 监听 127.0.0.1:8097

# 4. 前端
cd frontend && npm install && npm run dev      # http://localhost:5173
```

登录后到「我的 → 模型接口配置」新建渠道，Base URL 填 `http://127.0.0.1:8097/v1`，
Key 随便填（mock 只校验非空），测试连通 → 同步模型；再到「模型注册表」建一个对外模型并绑定
`mock-chat`，即可开始真实流式对话。接真实厂商时把 Base URL 与 Key 换成实际的即可，代码无需改动。

## 验证

```bash
cd backend && pytest -q                 # 143 项
ruff check app scripts && mypy app scripts
cd frontend && npm test                 # 19 项
npm run typecheck && npm run build
python scripts/e2e_reset.py && python scripts/e2e_check.py   # 17 步真实浏览器端到端
```

端到端覆盖：未登录跳转 → 首次强制改密 → 建渠道 → 连通测试 → 同步模型 → 建模型并绑定 →
建会话 → 流式对话与用量结算 → 建房间 → 房间 @AI → 我的页用量 → 主题切换 → 桌面双栏，
并断言 375/768/1440 三宽度无横向滚动、图标字体加载正常、控制台零错误。

## 部署

`deploy/` 下有五服务 Docker Compose、非 root 的 Dockerfile、以及 Caddyfile
（SSE 关缓冲 `flush_interval -1`、WebSocket 3600s 超时）。Caddyfile 已用真实 caddy 二进制校验通过。
**容器编排尚未在真实 Docker 环境跑过**，上线前需在目标机验证。
