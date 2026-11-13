# CLAUDE.md — LinkAI

多房间 AI 聊天平台：管理员配模型渠道，成员邀请码注册后单聊 AI，或在多人房间里 @AI 讨论。

## 唯一真相源

需求、数据模型、接口契约、业务规则、异常文案、开发陷阱全部在 **`docs/LinkAI-PRD-v1.md`**，本文档不重复其内容，冲突以 PRD 为准。视觉与交互以 `prototype-html/prototype-ai-chatroom-v6.html`（App）、`prototype-room-flow-v2.html`（房间流程与状态机）为准。

## 技术栈

- 后端 Python 3.12 + FastAPI + SQLAlchemy 2.0 异步 + asyncpg + Alembic + Pydantic v2
- 模型接入**协议驱动**：自研三协议适配器 `openai_compatible` / `anthropic` / `gemini`，选协议 + 填 base_url + Key 即可接入任意上游；V1 不引入 litellm（V2 可选）
- PostgreSQL 16 为真相源；Redis 7 负责配额计数、房间串行锁、限流、pub/sub 广播、在线状态
- 前端 Vue 3 + Vite + Pinia；**管理后台在桌面与移动端都是完整功能**（<768px 卡片+抽屉，≥1024px 表格+双栏），桌面用 Element Plus，成员端沿用原型设计令牌不引 UI 库
- 实时：WebSocket（房间广播）+ SSE（AI 流式回复），两套并存各司其职
- 部署：海外 VPS 单实例，Docker Compose 五容器（caddy/app/scheduler/postgres/redis），Caddy 自动 HTTPS
- 定时任务 APScheduler 独立容器且 `replicas=1`；V1 不引入 Celery

## 关键命令

```bash
cd backend && source .venv/bin/activate
docker compose -f deploy/docker-compose.dev.yml up -d postgres redis
alembic upgrade head && python -m scripts.seed
uvicorn app.main:app --reload --port 8000
pytest tests/smoke -q          # 写业务代码前必须先全绿
pytest -q                      # 独立测试库 + Redis db=15，上游模型全 mock
cd ../frontend && npm install && npm run dev    # :5173，代理 /api → :8000
ruff check backend && mypy backend/app && cd frontend && npm run lint && npm run build
```

## 禁止事项

- 不引入 PRD 第 22 章未列出的依赖；不直接改表结构，只走 Alembic 且必须实现 `downgrade()`
- 不改 `.env` 变量名；不硬编码密码、JWT、渠道 API Key；日志不输出上述任何一项与消息正文全文
- 渠道 Key 只返回 `api_key_hint`（末 4 位），任何接口不得返回明文或密文
- 不跳过 PRD 第 3 章权限校验（`require_admin` / `room_perm` / `scope_*`）；不用 `v-html` 渲染 AI 回复
- 关键写入（注册、发消息、@AI）必须幂等：`Idempotency-Key` + 唯一索引
- 生产必须 `DOCS_ENABLED=false`；每个功能完成须通过对应测试

## 开发红线（违反任意一条都会造成难定位的线上事故）

1. 写业务代码前先跑通 `tests/smoke/test_stack.py`（FastAPI 异步 + asyncpg + Redis + SSE + WebSocket + Alembic）
2. 时间统一 aware UTC，禁 `datetime.utcnow()`；但 `quota_date` 必须按 `Asia/Shanghai` 算——服务器在 UTC，直接用 `now().date()` 会让配额在早上 8 点重置
3. 禁止 lazy loading，关联查询显式 `selectinload()` / `joinedload()`，否则抛 `MissingGreenlet`
4. 配额禁止"先查后扣"，必须单条 `INSERT ... ON CONFLICT ... WHERE ... RETURNING`（PRD 5.6.2），返回空即超限；写完必跑并发超卖测试
5. 上游模型调用绝不能包在数据库事务内：预扣事务提交 → 调模型 → 另开结算事务；Redis PUBLISH 必须在事务提交后
6. `usage_logs.status='pending'` 必须落终态（settled/refunded/failed），scheduler 每 10 分钟兜底退回
7. 房间广播从第一天就走 Redis pub/sub，禁用进程内存字典——否则加第二个实例时消息串不过去，改造要动整条链路
8. Caddy 对 SSE 路径必须 `flush_interval -1`，否则流式失效，用户等几秒后一次性看到全文（最高频事故）
9. 单聊用 `conversations.active_call_id` 做会话级串行，并用 `generation_id` 防止旧流覆盖新回复
10. WebSocket 用一次性 ticket 建连，禁止把 JWT 放进 query string（会进访问日志与浏览器历史）
11. `conftest.py` 的 `clean_state` fixture 必须先于第一个测试文件设计；测试用独立库 + Redis db=15，清理按 FK 逆序
12. 容器内用服务名连 `postgres`/`redis`，禁 `localhost`；前端 API 地址从 `import.meta.env.VITE_API_BASE` 读，禁硬编码协议与域名
13. 主键统一 BIGINT identity；枚举统一小写字符串 + CHECK 约束（不用 PG enum 类型）；金额用 NUMERIC，禁 float
14. **上层代码永不接触厂商字段**：路由/配额/流式/结算只认 `UnifiedRequest` 与 `StreamEvent`（PRD 5.2.1），厂商差异全部关在 `adapter/{openai_compat,anthropic,gemini}.py` 内；新增厂商是加预设表一行，不是加代码分支
15. OpenAI 协议流式取 usage 必须请求带 `stream_options.include_usage=true`，否则拿不到 token 数、无法结算；Gemini 无流式终止标记，靠连接关闭判定；Anthropic 的 `max_tokens` 是必填
16. openai SDK 用 v1.x 风格 `client.chat.completions.create`，网上大量 v0.x 代码不兼容
17. 新增 Material Icons 图标名前必须实测渲染宽度等于 font-size，否则是缺字方框、会撑破布局（原型阶段踩过）
18. `scheduler` 容器必须 `replicas=1`；`--workers` 数变更时必须重算数据库连接数（pool 是每 worker 独立的）

## 开发规范与目录

代码风格与命名、Git 提交格式（`<type>(<scope>): <subject>`）、分支策略见 PRD 第 14.1 与本文档上方命令；文件级目录结构见 PRD 第 21 章：`backend/app/{api,services,models,schemas,core,tasks}`、`frontend/src/{views,components,stores,api,composables,styles}`、`deploy/`、`docs/`、`scripts/`。

---

内容由 AI 生成

## 系统结构（2026-11-13 重构后）

后端 backend/app/ 按系统垂直切分，每系统自带 api + services：
- core/ 核心系统：config/db/redis/security/crypto/errors/logging/ratelimit/idempotency/timeutil/startup
- users/ 用户系统（含群聊）：auth/friends/dm/rooms/templates/search + invite/audit/quote/dm_bus/room_bus
- files/ 文件系统：uploads/shares + upload/export 服务
- llm/ 大模型接入与输出系统：adapter(三协议)/channels/models/routing/quota/output_mode/drift/conversations
- stats/ 统计与可观测系统：feedback/live/precompute/experiments/channel_health/alerts/tasks/scheduler
- admin/ 治理系统：settings/用户管理/邀请码/渠道模型管理路由
- interfaces/ 接口系统：app 装配/deps/中间件/WS 端点/健康检查；app/main.py 为薄入口（uvicorn app.main:app 不变）

前端 frontend/src/：
- theme/ 统一主题UI令牌系统：tokens.css/base.css/icons/通用组件/theme store
- core/ 核心：router/auth/toast/sockets
- interfaces/ 接口层：api client/sse/types/resources/rooms
- users/ 用户视图（登录/好友/私聊/房间/消息列表等）
- files/ 文件视图与组件（AuthImage/ShareExportDrawer/分享页）
- llm/ 大模型视图（Chat/Channels/Models/StructuredView）
- stats/ 统计视图（Stats/Experiments/Sparkline）
- admin/ 治理视图（AdminLayout/Settings/Invites）

