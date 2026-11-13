# LinkAI — 多房间 AI 聊天平台
# Claude Code 开发规范文档 v1.0

**文档版本**: v1.1
**创建日期**: 2026-11-11
**项目代号**: ai-chatroom
**状态**: Final — 已完成 111 项扫雷审查（7 项 RED 全部修复）；v1.1 按决策改为**协议驱动的通用接入** + **桌面与移动端完整管理后台**
**开发工具**: Claude Code
**PRD Generator版本**: v4.0
**配套原型**: `prototype-html/prototype-ai-chatroom-v6.html`（App 交互原型）、`prototype-html/prototype-room-flow-v2.html`（房间流程与状态机规格）

> **本文档是 Claude Code 开发的唯一真相源。** 原型文件定义视觉与交互，本文档定义数据结构、接口契约与业务规则。两者冲突时以本文档为准，并在变更记录中登记。

---

## 1. 项目概述与目标

### 1.1 项目背景

管理员配置若干大模型接口（阿里百炼、DeepSeek、OpenAI 等），其他用户通过邀请码注册登录后，可以在单聊会话中调用 AI，也可以进入多人房间与其他成员和 AI 一起讨论。核心难点不在"调用模型"，而在**密钥安全、配额归属、成本控制与多厂商接入的统一抽象**。

### 1.2 V1 核心目标

一句话定位：**一个自托管的多房间 AI 聊天平台，管理员配一次接口，成员进来就能聊，成本可控可追溯。**

量化指标（V1 验收线）：

- AI 首字延迟 P95 ≤ 1.5s（不含上游模型自身耗时）
- 单次 @AI 调用的配额扣减误差为 0（预扣必结算或必退回，不允许悬挂）
- 支持 ≥ 5 个渠道并存，单渠道故障时 3s 内自动切换到备用渠道
- 100 注册用户 / 30 日活 / 峰值 20 并发下，普通消息发送 P95 ≤ 300ms
- 密钥在任何接口响应、日志、前端产物中零出现

### 1.3 目标用户

| 角色 | role 字段值 | 特征 | 核心需求 |
|------|------------|------|---------|
| 超级管理员 | `admin` | 项目所有者，通常 1 人 | 配渠道、控成本、管用户、看统计 |
| 房主 | `member` + `room_members.role='owner'` | 创建房间的普通用户 | 设房间主题提示词、绑定模型、控房间预算 |
| 房间管理员 | `member` + `room_members.role='manager'` | 房主指定 | 禁言、移出成员、审批入房 |
| 普通成员 | `member` | 邀请码注册 | 单聊 AI、进房间讨论、@AI 提问 |
| 游客 | 未登录 | — | 仅能看登录页与房间简介 |

注意：**"房主"不是 users.role 的值**，它是 `room_members` 表里的房间级角色。一个普通用户可以同时是 A 房间的房主和 B 房间的成员。全局角色只有 `admin` / `member` 两种，避免权限体系复杂化。

### 1.4 架构设计要点

- **单租户**：只有一套系统、一个管理员，无租户隔离需求。数据隔离维度是"用户"和"房间"，不是"租户"
- **无状态应用 + 有状态存储**：Web 进程无状态（会话在 JWT，广播在 Redis pub/sub），PostgreSQL 与 Redis 有状态
- **V1 单实例部署**，但**所有跨进程协调一律走 Redis**（配额计数、房间串行锁、消息广播、限流），为 V2 水平扩展预留，代码零改造即可加实例
- **模型接入采用「渠道 Channel」抽象**，对外统一 OpenAI 兼容格式，内部适配器翻译

---

## 2. 技术架构

### 2.1 技术栈

| 层 | 选型 | 版本约束 |
|----|------|---------|
| 运行时 | Python | 3.12.x |
| Web 框架 | FastAPI | `~=0.115` |
| ASGI 服务器 | Uvicorn | `~=0.32` |
| ORM | SQLAlchemy（异步） | `~=2.0` |
| 异步驱动 | asyncpg | `~=0.30` |
| 迁移 | Alembic | `~=1.14` |
| 校验 | Pydantic | `~=2.9` |
| 模型 SDK | openai | `~=1.55` |
| 协议适配 | 自研三协议适配器：`openai_compatible` / `anthropic` / `gemini` | 无额外依赖；litellm 降为 **V2 可选**兜底 |
| HTTP 客户端 | httpx | `~=0.27` |
| 定时任务 | APScheduler | `~=3.10` |
| 认证 | PyJWT | `~=2.9` |
| 密码哈希 | argon2-cffi | `~=23.1` |
| 字段加密 | cryptography（Fernet） | `~=43.0` |
| Redis 客户端 | redis-py | `~=5.2` |
| 日志 | structlog | `~=24.4` |
| 前端框架 | Vue | `~=3.5` |
| 构建 | Vite | `~=6.0` |
| 状态管理 | Pinia | `~=2.2` |
| 路由 | Vue Router | `~=4.4` |
| 桌面端 UI 库 | Element Plus | `~=2.8`（仅管理后台使用） |
| 数据库 | PostgreSQL | 16.x |
| 缓存/协调 | Redis | 7.2.x |
| 反向代理 | Caddy | 2.8.x（自动 HTTPS） |
| 容器 | Docker + Docker Compose | Compose v2 |
| 测试 | pytest + pytest-asyncio + httpx | `~=8.3` / `~=0.24` |

**版本锁定规则**：上表为兼容版本约束。脚手架搭好、最小异步 smoke test 跑通后，**必须执行 `pip freeze > requirements.txt` 与 `npm ls --depth=0` 固化出三段式精确版本**并提交仓库。此后禁止使用无上界的 `>=`。

### 2.2 技术选型理由

- **Python + FastAPI**：AI 生态最完整，各家模型 SDK 首先支持 Python；异步原生支持 SSE 与 WebSocket；AI 编程工具生成质量最高
- **不选 Go**：本项目峰值 < 100 QPS，Go 的并发优势用不上，反而失去 AI SDK 生态
- **PostgreSQL 而非 SQLite**：房间多人并发写消息 + 配额原子扣减，SQLite 写锁会成为瓶颈；PG 同机部署成本为 0
- **Caddy 而非 Nginx**：自动申请与续期证书，配置量小一个数量级，SSE 关缓冲只需一行
- **协议驱动而非厂商驱动（v1.1 核心决策）**：渠道的 `type` 表示**协议类型**而非厂商。管理员选一种协议、填 base_url 与 Key，任何遵守该协议的上游都能直接接入，无需为新厂商改代码。V1 实现三种协议适配器：
  - `openai_compatible` —— 覆盖面最广：OpenAI、DeepSeek、阿里百炼、SiliconFlow、OpenRouter、Groq、Moonshot、智谱、Together、Ollama、vLLM 全部走这一个适配器
  - `anthropic` —— Anthropic Messages 协议（含各类兼容代理）
  - `gemini` —— Google Gemini `generateContent` 协议（AI Studio 的 API Key 模式）
- **V1 不引入 litellm**：三协议自研适配器总量约 400-600 行，比接入 litellm 的抽象层更可控，并消除其迭代极快、偶有破坏性变更的版本漂移风险；litellm 保留为 V2 选项，用于接入第四种以上的冷门协议
- **不部署 One API/New API 作独立网关**：它们的令牌额度体系会与本项目"房间配额归属房主 + @AI 触发 + 房间串行队列"的自定义规则冲突，等于维护两套账本
- **借鉴而非依赖**：渠道抽象、模型名映射、权重优先级路由、失败自动禁用、冷却窗口、参数白名单、预算预扣先于路由、call_id 全链路追踪、流式零拷贝透传——这些设计取自 One API / New API / LiteLLM 的成熟实践，在本项目中自行实现（详见 5.3、5.6）

### 2.3 系统架构图

```
                        ┌─────────────────────────────────────┐
   手机浏览器 / 桌面浏览器 │            Caddy (443)               │
   ────────────────────►│  自动 HTTPS · 反代 · 静态资源 · 关缓冲  │
                        └───────────┬─────────────────────────┘
                                    │
                 ┌──────────────────┼───────────────────┐
                 │ /  (静态)         │ /api/*  /ws/*      │
                 ▼                  ▼                    ▼
        ┌────────────────┐  ┌──────────────────────────────────┐
        │  Vue 3 dist    │  │      FastAPI (Uvicorn, 无状态)    │
        │  移动端 + 桌面端 │  │  ┌────────────────────────────┐  │
        └────────────────┘  │  │ Router: auth/conv/room/     │  │
                            │  │  model/admin/stats/ws       │  │
                            │  ├────────────────────────────┤  │
                            │  │ Service 层                   │  │
                            │  │  · quota  预扣/结算/退回      │  │
                            │  │  · router 渠道选路/故障转移    │  │
                            │  │  · streamer SSE 透传          │  │
                            │  │  · broadcast 房间广播         │  │
                            │  ├────────────────────────────┤  │
                            │  │ Adapter 层                   │  │
                            │  │  openai / anthropic / gemini │  │
                            │  └────────────────────────────┘  │
                            └───┬──────────┬──────────┬────────┘
                                │          │          │
                    ┌───────────▼──┐  ┌────▼─────┐  ┌─▼──────────────┐
                    │ PostgreSQL16 │  │ Redis 7  │  │ scheduler 容器  │
                    │ 12 张表       │  │ 配额计数  │  │ APScheduler     │
                    │ 业务真相源     │  │ 房间串行锁 │  │ 独立单进程       │
                    └──────────────┘  │ 限流      │  │ · 渠道健康巡检   │
                                      │ pub/sub   │  │ · 配额日切对账   │
                                      │ 在线状态   │  │ · 备份 · 归档    │
                                      └──────────┘  └────────────────┘
                                                          │
                        ┌─────────────────────────────────┼──────────────┐
                        ▼                                 ▼              ▼
              ┌──────────────────┐            ┌──────────────┐  ┌──────────────┐
              │ 阿里百炼 / DeepSeek│            │ OpenAI / Groq │  │ Anthropic /  │
              │ (OpenAI 兼容)     │            │ (OpenAI 兼容) │  │ Gemini(原生)  │
              └──────────────────┘            └──────────────┘  └──────────────┘
                        经 openai 适配器              经 openai 适配器    经 anthropic/gemini 适配器
```

### 2.4 服务依赖与启动顺序

```
PostgreSQL → Redis → app → scheduler → Caddy

健康检查门槛：
- app 启动前：postgres 可执行 SELECT 1（最多重试 10 次 × 3s，超时退出而非无限等待）
- app 启动前：redis 可执行 PING（同上）
- scheduler 启动前：app 的 /api/health 返回 200
- Caddy 无依赖，最后启动
```

### 2.5 有状态 / 无状态标注

| 组件 | 状态 | 水平扩展难度 | 说明 |
|------|------|------------|------|
| FastAPI app | 无状态 | 容易 | 会话在 JWT，广播在 Redis pub/sub，可直接加实例 |
| scheduler | 有状态（调度表在内存） | 需选主 | **必须单实例**；若将来多实例需加 Redis 分布式锁 |
| PostgreSQL | 有状态 | 需主从 | V1 单机；V2 加只读副本分担统计查询 |
| Redis | 有状态 | 需哨兵/集群 | 配额计数丢失可由 daily_usage 表重算（见 5.6.5） |
| Caddy | 无状态 | 容易 | 证书存卷，需共享或各实例自签 |

---

## 3. 权限体系

### 3.1 权限矩阵（角色 × 功能 × 数据范围）

| 功能 | admin | 房主 | 房间管理员 | 普通成员 | 游客 | 数据范围 |
|------|-------|------|-----------|---------|------|---------|
| 注册 / 登录 | ✓ | ✓ | ✓ | ✓ | ✓ | 自己 |
| 查看自己的会话与消息 | ✓ | ✓ | ✓ | ✓ | ✗ | 仅自己 |
| 创建单聊会话、发消息、@AI | ✓ | ✓ | ✓ | ✓ | ✗ | 仅自己 |
| 创建房间 | ✓ | ✓ | ✓ | ✓ | ✗ | 自己成为房主 |
| 进入公开房间 | ✓ | ✓ | ✓ | ✓ | ✗ | 已加入的房间 |
| 进入受限房间 | ✓ | ✓ | ✓ | 需邀请码/审批 | ✗ | 同上 |
| 房间内发言 | ✓ | ✓ | ✓ | ✓（未禁言） | ✗ | 本房间 |
| 房间内 @AI | ✓ | ✓ | ✓ | ✓（受冷却） | ✗ | 本房间 |
| 查看房间历史消息 | ✓ | ✓ | ✓ | ✓ | 仅房间简介 | 本房间 |
| 邀请成员 | ✓ | ✓ | ✓ | 由房主配置 | ✗ | 本房间 |
| 禁言 / 移出成员 | ✓ | ✓ | ✓ | ✗ | ✗ | 本房间，不可操作房主 |
| 审批入房申请 | ✓ | ✓ | ✓ | ✗ | ✗ | 本房间 |
| 修改房间提示词 / 预算 / 模型 | ✓ | ✓ | 提示词可配置 | ✗ | ✗ | 本房间 |
| 关闭 / 归档房间 | ✓ | ✓ | ✗ | ✗ | ✗ | 本房间 |
| 查看房间用量 | ✓ 全部 | ✓ 本房间明细 | 仅汇总 | 仅自己触发部分 | ✗ | 分级 |
| 渠道 CRUD / 连通性测试 | ✓ | ✗ | ✗ | ✗ | ✗ | 全局 |
| 模型注册表 CRUD | ✓ | ✗ | ✗ | ✗ | ✗ | 全局 |
| 用户管理（封禁/重置密码/改配额） | ✓ | ✗ | ✗ | ✗ | ✗ | 全局 |
| 邀请码发放 | ✓ | ✗ | ✗ | ✗ | ✗ | 全局 |
| 全局用量统计 | ✓ | ✗ | ✗ | ✗ | ✗ | 全局 |
| 系统设置（限额/注册方式/敏感词） | ✓ | ✗ | ✗ | ✗ | ✗ | 全局 |
| 查看审计日志 | ✓ | ✗ | ✗ | ✗ | ✗ | 全局 |

### 3.2 数据过滤规则（伪代码）

```python
# 会话与消息：只能访问自己的
def scope_conversation(user, conv_id):
    conv = get_conv(conv_id)
    if conv is None: raise HTTP404
    if user.role != 'admin' and conv.user_id != user.id: raise HTTP403

# 房间消息：必须是房间成员（admin 例外）
def scope_room(user, room_id):
    room = get_room(room_id)
    if room is None or room.archived: raise HTTP404
    if user.role == 'admin': return room
    if not is_member(room_id, user.id): raise HTTP403
    return room

# 房间内操作权限：按 room_members.role 判定，admin 全局放行
def room_perm(user, room_id, need: Literal['owner','manager','member']):
    if user.role == 'admin': return True
    rm = get_room_member(room_id, user.id)
    if rm is None: return False
    order = {'member': 0, 'manager': 1, 'owner': 2}
    return order[rm.role] >= order[need]

# 用量数据分级
def scope_usage(user, room_id=None):
    if user.role == 'admin': return All()
    if room_id and room_perm(user, room_id, 'owner'): return RoomAll(room_id)
    if room_id and room_perm(user, room_id, 'manager'): return RoomSummary(room_id)
    return OwnOnly(user.id)
```

### 3.3 关键权限逻辑

```python
# 管理员依赖注入
async def require_admin(user = Depends(get_current_user)):
    if user.role != 'admin':
        raise HTTPException(403, code="FORBIDDEN_ADMIN_ONLY")
    return user

# 房间 @AI 四连校验（顺序不可调换，见 5.6.1）
async def guard_room_ai(user, room, settings):
    if user.status != 'active':            raise Blocked("账号不可用")
    if room.ai_status in ('suspended','closed'): raise Blocked(room_ai_reason(room))
    if is_muted(room.id, user.id):         raise Blocked("你在本房间被禁言")
    if not cooldown_ok(room.id, user.id):  raise TooSoon("冷却中，请 N 秒后再试")
    if not daily_msg_ok(user):             raise Quota("今日消息已达上限")
    if not budget_ok(room, user):          raise Quota("房间或你的额度已用完")
```

### 3.4 前端路由守卫

| 路由 | 要求 |
|------|------|
| `/login`、`/register` | 已登录则跳 `/msgs` |
| `/msgs`、`/rooms`、`/me`、`/c/:id`、`/r/:id` | 需登录 |
| `/r/:id` | 需登录 **且** 是该房间成员，否则跳 `/rooms` 并提示 |
| `/admin/*`（渠道、模型、用户、统计、邀请码、设置） | 需登录 **且** `role==='admin'`，否则跳 `/403` |

守卫实现：路由 meta 标 `requiresAuth` / `requiresAdmin` / `requiresMembership`；token 过期（401）统一清 Pinia 状态并跳登录页，携带 `redirect` 参数回跳。

**首次改密拦截**：`GET /api/auth/me` 返回 `must_change_password`；为 true 时前端强制跳 `/password` 并拦截其他所有路由。后端同步校验：该标记为 true 的用户除 `/api/auth/me`、`/api/auth/password`、`/api/auth/logout` 外一律返回 `403 PASSWORD_CHANGE_REQUIRED`（**不能只靠前端拦截**）。种子 admin 与"管理员重置他人密码"都会置 true。

### 3.5 敏感操作二次确认清单

| 操作 | 确认方式 |
|------|---------|
| 删除渠道 | 输入渠道名称 |
| 删除房间 / 归档房间 | 输入房间名称 |
| 封禁用户 | 输入管理员密码 |
| 重置他人密码 | 输入管理员密码 |
| 清空会话 / 清空房间上下文 | 二次弹窗确认 |
| 修改全局配额与注册方式 | 二次弹窗确认 |
| 批量删除消息记录 | 输入管理员密码 |

---

## 4. 数据模型

### 4.1 ER 关系图

```
invite_codes ──created_by──► users ◄──invited_by── users
                              │
        ┌─────────────────────┼──────────────────────┬────────────────┐
        │                     │                      │                │
   conversations           rooms ──owner_id──►   usage_logs        audit_logs
        │                     │                 (user_id/owner_id)  (actor_id)
        │              room_members                │
        │              room_join_requests      daily_usage
        │                     │
        └──────► messages ◄────┘
                   │  (scope='dm'|'room' 二选一)
                   ├── model_id ──► models ──┐
                   ├── channel_id ───────────┤
                   └── usage_log_id ──► usage_logs
                                             │
                    model_channels ──────────┤
                    (model_id, channel_id, upstream_model)
                                             │
                                         channels
                                             │
                                         settings（独立键值表）
```

### 4.2 完整 DDL

```sql
-- 扩展
CREATE EXTENSION IF NOT EXISTS citext;      -- 邮箱大小写不敏感唯一
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid()

-- 1. 用户
CREATE TABLE users (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email             CITEXT UNIQUE,
  phone             VARCHAR(20) UNIQUE,
  password_hash     VARCHAR(255) NOT NULL,
  nickname          VARCHAR(32)  NOT NULL,
  role              VARCHAR(16)  NOT NULL DEFAULT 'member'
                    CHECK (role IN ('admin','member')),
  status            VARCHAR(16)  NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','muted','banned')),
  mute_until        TIMESTAMPTZ,
  daily_msg_limit   INT     NOT NULL DEFAULT 50,
  daily_token_limit BIGINT  NOT NULL DEFAULT 100000,
  invited_by        BIGINT  REFERENCES users(id) ON DELETE SET NULL,
  invite_code_used  VARCHAR(24),
  must_change_password BOOLEAN NOT NULL DEFAULT false,   -- 种子 admin 与重置密码后置 true
  last_login_at     TIMESTAMPTZ,
  last_login_ip     INET,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (email IS NOT NULL OR phone IS NOT NULL)
);
COMMENT ON TABLE users IS '全局角色只有 admin/member；房主等房间角色在 room_members';

-- 2. 邀请码
CREATE TABLE invite_codes (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        VARCHAR(24) NOT NULL UNIQUE,
  created_by  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  max_uses    INT NOT NULL DEFAULT 1 CHECK (max_uses > 0),
  used_count  INT NOT NULL DEFAULT 0,
  expires_at  TIMESTAMPTZ,
  note        VARCHAR(128),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (used_count <= max_uses)
);

-- 3. 渠道（上游模型接口凭证）
CREATE TABLE channels (
  id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name                   VARCHAR(64) NOT NULL,
  -- type 表示【协议类型】而非厂商：选定协议后，任何遵守该协议的上游都可直接接入
  type                   VARCHAR(24) NOT NULL DEFAULT 'openai_compatible'
                         CHECK (type IN ('openai_compatible','anthropic','gemini','custom')),
  preset                 VARCHAR(32),                    -- 厂商预设标识，仅界面回显，不参与路由
  base_url               VARCHAR(255) NOT NULL,
  api_key_enc            TEXT NOT NULL,                 -- Fernet 密文
  api_key_hint           VARCHAR(16) NOT NULL,          -- 末 4 位，仅展示用
  discovered_models      JSONB NOT NULL DEFAULT '[]',   -- 同步模型列表的缓存
  supported_params       JSONB NOT NULL DEFAULT
                         '["temperature","top_p","max_tokens","stream"]',
  weight                 INT NOT NULL DEFAULT 100 CHECK (weight >= 0),
  priority               INT NOT NULL DEFAULT 0,
  status                 VARCHAR(16) NOT NULL DEFAULT 'enabled'
                         CHECK (status IN ('enabled','disabled','auto_disabled')),
  fail_count             INT NOT NULL DEFAULT 0,
  success_count          INT NOT NULL DEFAULT 0,
  cooldown_until         TIMESTAMPTZ,
  last_check_at          TIMESTAMPTZ,
  last_latency_ms        INT,
  timeout_first_token_ms INT NOT NULL DEFAULT 15000,
  timeout_total_ms       INT NOT NULL DEFAULT 60000,
  remark                 VARCHAR(255),
  version                INT NOT NULL DEFAULT 0,        -- 乐观锁，PATCH 时比对
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN channels.api_key_enc IS 'Fernet 加密，密钥来自 env CHANNEL_CIPHER_KEY；明文永不落库、永不出接口';
COMMENT ON COLUMN channels.type IS '协议类型：openai_compatible / anthropic / gemini / custom。适配器按此字段分发，与厂商无关';

-- 4. 对外模型注册表
CREATE TABLE models (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  public_name       VARCHAR(64) NOT NULL UNIQUE,   -- 对外暴露名，如 smart/fast/qwen-max
  display_name      VARCHAR(64) NOT NULL,
  tier              VARCHAR(16) NOT NULL DEFAULT 'standard'
                    CHECK (tier IN ('fast','standard','premium')),
  context_limit     INT NOT NULL DEFAULT 32768,
  max_output_tokens INT NOT NULL DEFAULT 4096,
  price_input       NUMERIC(12,6) NOT NULL DEFAULT 0,   -- 元 / 百万 token
  price_output      NUMERIC(12,6) NOT NULL DEFAULT 0,
  currency          CHAR(3) NOT NULL DEFAULT 'CNY',
  enabled           BOOLEAN NOT NULL DEFAULT true,
  is_default        BOOLEAN NOT NULL DEFAULT false,
  sort_order        INT NOT NULL DEFAULT 0,
  version           INT NOT NULL DEFAULT 0,             -- 乐观锁
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 全局只能有一个默认模型
CREATE UNIQUE INDEX uniq_models_single_default ON models (is_default) WHERE is_default;

-- 5. 模型 ↔ 渠道 绑定（承载"模型名映射"）
CREATE TABLE model_channels (
  model_id       BIGINT NOT NULL REFERENCES models(id)   ON DELETE CASCADE,
  channel_id     BIGINT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  upstream_model VARCHAR(128) NOT NULL,      -- 上游真实模型名
  enabled        BOOLEAN NOT NULL DEFAULT true,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (model_id, channel_id)
);
COMMENT ON TABLE model_channels IS '替代 One API 的 model_mapping JSON：可索引、可外键、路由无需扫 JSONB';

-- 6. 单聊会话
CREATE TABLE conversations (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title           VARCHAR(64) NOT NULL DEFAULT '新会话',
  model_id        BIGINT REFERENCES models(id) ON DELETE SET NULL,
  system_prompt   TEXT,
  pinned          BOOLEAN NOT NULL DEFAULT false,
  notify_muted    BOOLEAN NOT NULL DEFAULT false,
  active_call_id  UUID,                    -- 进行中的 AI 调用，非空即表示有流在跑（会话级串行）
  context_tokens  INT NOT NULL DEFAULT 0,
  message_count   INT NOT NULL DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7. 房间
CREATE TABLE rooms (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name               VARCHAR(64) NOT NULL,
  description        VARCHAR(255),
  owner_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  system_prompt      TEXT NOT NULL DEFAULT '',
  model_id           BIGINT REFERENCES models(id) ON DELETE SET NULL,
  access_type        VARCHAR(16) NOT NULL DEFAULT 'public'
                     CHECK (access_type IN ('public','invite_code','approval')),
  invite_code        VARCHAR(16) UNIQUE,
  max_members        INT NOT NULL DEFAULT 50 CHECK (max_members > 0),
  member_count       INT NOT NULL DEFAULT 0,
  daily_token_budget BIGINT NOT NULL DEFAULT 500000,
  ai_status          VARCHAR(16) NOT NULL DEFAULT 'normal'
                     CHECK (ai_status IN ('normal','warning','suspended','closed')),
  ai_trigger         VARCHAR(16) NOT NULL DEFAULT 'mention'
                     CHECK (ai_trigger IN ('mention','every','off')),
  context_window     INT NOT NULL DEFAULT 20,      -- 组装上下文取最近 N 条
  allow_member_invite BOOLEAN NOT NULL DEFAULT true,
  archived           BOOLEAN NOT NULL DEFAULT false,
  version            INT NOT NULL DEFAULT 0,            -- 乐观锁（房主与管理员可能同时改）
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. 房间成员
CREATE TABLE room_members (
  room_id          BIGINT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  user_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role             VARCHAR(16) NOT NULL DEFAULT 'member'
                   CHECK (role IN ('owner','manager','member')),
  muted_until      TIMESTAMPTZ,
  notify_muted     BOOLEAN NOT NULL DEFAULT false,   -- 房间免打扰（原型「房间操作」弹层）
  nickname_in_room VARCHAR(32),
  last_read_msg_id BIGINT,
  joined_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (room_id, user_id)
);

-- 9. 入房申请
CREATE TABLE room_join_requests (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  room_id    BIGINT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  message    VARCHAR(255),
  status     VARCHAR(16) NOT NULL DEFAULT 'pending'
             CHECK (status IN ('pending','approved','rejected','expired')),
  decided_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  decided_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 同一用户对同一房间只能有一条待审申请（PG15+ NULLS NOT DISTINCT 不适用，用部分唯一索引）
CREATE UNIQUE INDEX uniq_pending_join_request ON room_join_requests (room_id, user_id)
  WHERE status = 'pending';

-- 10. 用量账本（一次 AI 调用一条）
CREATE TABLE usage_logs (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  call_id       UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- 触发者
  owner_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- 计费归属
  room_id       BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  conversation_id BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
  model_id      BIGINT REFERENCES models(id) ON DELETE SET NULL,
  channel_id    BIGINT REFERENCES channels(id) ON DELETE SET NULL,
  -- 快照字段：模型/渠道被删除后历史统计仍可正确归维度，不依赖 JOIN
  model_public_name  VARCHAR(64),
  model_display_name VARCHAR(64),
  channel_name  VARCHAR(64),
  status        VARCHAR(16) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','settled','refunded','failed')),
  frozen_tokens BIGINT NOT NULL DEFAULT 0,
  prompt_tokens INT,
  completion_tokens INT,
  total_tokens  INT,
  cost          NUMERIC(12,6) NOT NULL DEFAULT 0,
  quota_date    DATE NOT NULL,          -- Asia/Shanghai 当日日期，见 12.1
  first_token_ms INT,
  total_ms      INT,
  queue_pos     SMALLINT,
  retry_count   SMALLINT NOT NULL DEFAULT 0,
  fail_reason   VARCHAR(255),
  trace_id      UUID,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  settled_at    TIMESTAMPTZ
);

-- 11. 消息（单聊与房间共用一张表，scope 区分）
CREATE TABLE messages (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope              VARCHAR(8) NOT NULL CHECK (scope IN ('dm','room')),
  conversation_id    BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
  room_id            BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  sender_id          BIGINT REFERENCES users(id) ON DELETE SET NULL,  -- AI 消息为 NULL
  role               VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','system')),
  content            TEXT NOT NULL,
  content_blocked    BOOLEAN NOT NULL DEFAULT false,   -- 命中敏感词被拦截
  model_id           BIGINT REFERENCES models(id) ON DELETE SET NULL,
  channel_id         BIGINT REFERENCES channels(id) ON DELETE SET NULL,
  usage_log_id       BIGINT REFERENCES usage_logs(id) ON DELETE SET NULL,
  trigger_message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
  reply_to_msg_id    BIGINT REFERENCES messages(id) ON DELETE SET NULL,
  prompt_tokens      INT,
  completion_tokens  INT,
  total_tokens       INT,
  cost               NUMERIC(12,6),
  first_token_ms     INT,
  total_ms           INT,
  status             VARCHAR(16) NOT NULL DEFAULT 'ok'
                     CHECK (status IN ('ok','timeout','failed','blocked','refunded','streaming')),
  idempotency_key    UUID,
  generation_id      UUID,               -- 重新生成时的代次，旧代流不落库
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    (scope = 'dm'   AND conversation_id IS NOT NULL AND room_id IS NULL) OR
    (scope = 'room' AND room_id IS NOT NULL AND conversation_id IS NULL)
  ),
  CHECK (
    (role = 'assistant' AND sender_id IS NULL) OR
    (role <> 'assistant')
  )
);

-- 12. 每日用量汇总（配额判定与统计的数据源，Redis 的重算兜底）
CREATE TABLE daily_usage (
  quota_date        DATE NOT NULL,
  owner_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  room_id           BIGINT REFERENCES rooms(id) ON DELETE CASCADE,  -- NULL = 用户级
  msg_count         INT NOT NULL DEFAULT 0,
  ai_call_count     INT NOT NULL DEFAULT 0,
  prompt_tokens     BIGINT NOT NULL DEFAULT 0,
  completion_tokens BIGINT NOT NULL DEFAULT 0,
  total_tokens      BIGINT NOT NULL DEFAULT 0,
  cost              NUMERIC(14,6) NOT NULL DEFAULT 0,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (quota_date, owner_id, room_id)
);
COMMENT ON TABLE daily_usage IS 'room_id 为 NULL 表示用户级配额；非 NULL 表示该房间预算。两者独立累加，取先到者熔断';

-- 13. 审计日志
CREATE TABLE audit_logs (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
  action      VARCHAR(64) NOT NULL,        -- 如 channel.create / user.ban / room.ai_suspended
  target_type VARCHAR(32),
  target_id   VARCHAR(64),
  detail      JSONB NOT NULL DEFAULT '{}',
  ip          INET,
  trace_id    UUID,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 14. 站内通知（原型消息列表的「系统通知」聚合行）
CREATE TABLE notifications (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type       VARCHAR(32) NOT NULL
             CHECK (type IN ('system','quota_warn','quota_exceeded','room_ai_suspended',
                             'room_join_request','room_invite','mention','admin_action')),
  title      VARCHAR(64) NOT NULL,
  body       VARCHAR(500) NOT NULL DEFAULT '',
  link       VARCHAR(128),                  -- 前端跳转目标，如 /r/7 或 /admin/channels
  room_id    BIGINT REFERENCES rooms(id) ON DELETE CASCADE,
  is_read    BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 15. 运行时配置
CREATE TABLE settings (
  key        VARCHAR(64) PRIMARY KEY,
  value      JSONB NOT NULL,
  version    INT NOT NULL DEFAULT 0,                    -- 乐观锁
  updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 4.3 JSONB 字段结构示例

```jsonc
// channels.discovered_models —— 「同步模型列表」的结果缓存
[
  {"id": "qwen-max", "context_length": 32768, "owned_by": "dashscope"},
  {"id": "qwen-plus", "context_length": 131072, "owned_by": "dashscope"}
]

// channels.supported_params —— 参数白名单，发请求前按此过滤
["temperature", "top_p", "max_tokens", "stream", "stop"]

// audit_logs.detail
{
  "before": {"status": "enabled"},
  "after":  {"status": "auto_disabled"},
  "reason": "consecutive_failures=3, last_error=upstream_timeout"
}

// settings.value 示例
// key = "quota"
{"daily_msg_limit": 50, "daily_token_limit": 100000, "room_daily_token_budget": 500000,
 "warn_ratio": 0.8, "reset_tz": "Asia/Shanghai"}
// key = "registration"
{"mode": "invite_code", "require_invite": true}
// key = "moderation"
{"enabled": true, "block_input": true, "block_output": true, "wordlist_version": 3}
// key = "feature_flags"
{"room_ai": true, "web_search": false, "voice_input": false, "file_upload": false}
```

### 4.4 索引清单

```sql
-- 查询热点：会话列表、消息翻页、房间消息、用量聚合、审计检索
CREATE INDEX idx_conv_user_last      ON conversations (user_id, last_message_at DESC);
CREATE INDEX idx_msg_conv            ON messages (conversation_id, id DESC);
CREATE INDEX idx_msg_room            ON messages (room_id, id DESC);
CREATE INDEX idx_msg_room_created    ON messages (room_id, created_at DESC);
CREATE INDEX idx_msg_sender          ON messages (sender_id, created_at DESC);
CREATE INDEX idx_room_owner          ON rooms (owner_id);
CREATE INDEX idx_room_active         ON rooms (archived, member_count DESC);
CREATE INDEX idx_room_member_user    ON room_members (user_id, joined_at DESC);
CREATE INDEX idx_joinreq_room_status ON room_join_requests (room_id, status);
CREATE INDEX idx_usage_owner_date    ON usage_logs (owner_id, quota_date);
CREATE INDEX idx_usage_room_date     ON usage_logs (room_id, quota_date);
CREATE INDEX idx_usage_status        ON usage_logs (status) WHERE status = 'pending';
CREATE INDEX idx_usage_created       ON usage_logs (created_at DESC);
CREATE INDEX idx_usage_call          ON usage_logs (call_id);
CREATE INDEX idx_daily_owner         ON daily_usage (owner_id, quota_date DESC);
CREATE INDEX idx_daily_room          ON daily_usage (room_id, quota_date DESC);
CREATE INDEX idx_audit_action_time   ON audit_logs (action, created_at DESC);
CREATE INDEX idx_audit_actor         ON audit_logs (actor_id, created_at DESC);
CREATE INDEX idx_channel_status      ON channels (status, priority DESC, weight DESC);
CREATE INDEX idx_modelchannel_channel ON model_channels (channel_id);
CREATE INDEX idx_invite_unused       ON invite_codes (used_count, expires_at);
CREATE INDEX idx_notify_user_unread  ON notifications (user_id, is_read, created_at DESC);
CREATE INDEX idx_conv_active_call    ON conversations (active_call_id) WHERE active_call_id IS NOT NULL;
-- 幂等：同一用户对同一会话的重复提交
CREATE UNIQUE INDEX uniq_msg_idem    ON messages (idempotency_key) WHERE idempotency_key IS NOT NULL;
```

### 4.5 迁移策略

- 工具：**Alembic**（异步模式，`env.py` 用 `run_sync` 包装 + `asyncpg` URL）
- 规则：任何表结构变更必须通过 `alembic revision --autogenerate` 生成脚本并人工复核，**禁止手改数据库**
- 每个迁移脚本必须实现 `downgrade()`；不可逆变更（删列）需在 PR 描述中显式声明
- 多 head 时用 `alembic merge` 合并，禁止 `alembic stamp` 绕过

### 4.6 大表迁移注意

`messages` 与 `usage_logs` 是增长最快的表。超过 500 万行后：

- 加索引改用 `CREATE INDEX CONCURRENTLY`（不可在事务内执行）
- 加列必须 `NULL` 或带非常量默认值，避免全表重写
- 改列类型走"新列 + 双写 + 回填 + 切换"四步，不做原地 ALTER

### 4.7 数据增长预估与归档

| 表 | 月增长（100 用户 / 30 日活） | 归档策略 |
|----|---------------------------|---------|
| messages | 约 5-15 万行 | 保留 12 个月；超期分区归档到 `messages_archive` 或导出 CSV 后删除 |
| usage_logs | 约 1-3 万行 | 保留 12 个月，聚合结果已在 daily_usage，明细可归档 |
| daily_usage | 约 1000 行 | 永久保留（体量极小，是成本对账依据） |
| audit_logs | 约 2000 行 | 保留 24 个月 |
| 其余表 | < 1000 行 | 无需归档 |

V1 建议按月对 `messages` 做**声明式分区**（`PARTITION BY RANGE (created_at)`）预留能力，但初版可不分区，等超 200 万行再改（改造需停机或用 pg_partman）。

---

## 5. 功能模块详细说明

### 5.1 认证与注册

**功能描述**：邮箱 + 密码注册登录，邀请码准入，JWT 鉴权。

**业务规则**

- 注册方式由 `settings.registration.mode` 控制：`open`（开放）/ `invite_code`（邀请码必填）/ `closed`（仅管理员创建）
- 邀请码校验：存在 + `used_count < max_uses` + 未过期，注册成功后 `used_count += 1`（原子 UPDATE 带条件）
- 密码：最少 8 位，须含字母与数字；argon2id 哈希（`time_cost=3, memory_cost=65536, parallelism=4`）
- 登录失败锁定：同一账号连续失败 5 次锁定 15 分钟（Redis 计数）；同一 IP 连续失败 20 次锁定 1 小时
- JWT：access token 有效期 7 天，HS256，密钥来自 env；payload 含 `sub`(user_id)、`role`、`iat`、`exp`、`jti`
- 封禁/退出即时生效：Redis 维护 `token_blacklist:{jti}`，TTL = token 剩余有效期

**异常处理**

| 情况 | HTTP | 用户看到 |
|------|------|---------|
| 邮箱已注册 | 409 | "该邮箱已注册，去登录？" |
| 邀请码无效/已用完/过期 | 422 | "邀请码无效或已被使用" |
| 密码错误 | 401 | "邮箱或密码错误"（不区分是哪个错，防枚举） |
| 账号被封禁 | 403 | "账号已被停用，请联系管理员"（附申诉邮箱） |
| 锁定中 | 429 | "尝试过于频繁，请 N 分钟后重试" |

**数据流向**：`POST /api/auth/register` → `AuthService.register` → 校验邀请码 → 写 `users` + 更新 `invite_codes` + 写 `audit_logs` → 返回 token + 用户信息。

**幂等性**：注册用 `email`/`phone` 唯一约束兜底；客户端提交带 `Idempotency-Key`，服务端 10 分钟内同键返回首次结果。

### 5.2 渠道管理（管理员）

**功能描述**：增删改查上游模型接口，测试连通性，同步模型列表，启用/停用。

**业务规则**

- **新建渠道第一步是选协议类型**，选定后表单按协议动态渲染必填项（anthropic 需 `anthropic-version`；gemini 需选择 Key 传递方式），并给出该协议下的厂商预设下拉（一键填 base_url 与默认超时）；预设值只是便利，**最终以「测试连通性」实测通过为准**
- API Key 写入时用 Fernet 加密存 `api_key_enc`，同时存末 4 位到 `api_key_hint`；**任何查询接口只返回 hint，永不返回密文或明文**
- `supported_params` 按协议给默认值，管理员可增删；发请求前按此过滤，避免把上游不支持的参数发过去导致 400
- "测试连通性"：用该渠道发一次 `max_tokens=8` 的最小请求，记录 `last_latency_ms`、`last_check_at`，不落 `usage_logs`（不计费、不占配额）
- "同步模型列表"：调上游 `GET {base_url}/models`，结果写 `discovered_models`；管理员可勾选导入到 `models` + `model_channels`
- 停用渠道时：若该渠道是某个已启用模型的**唯一**绑定，则同时把该模型 `enabled=false`，并在响应里告知影响的模型与房间
- **管理员自我保护（后端强校验，不依赖前端）**：禁止封禁或降级自己；禁止封禁/降级系统内最后一个 `role='admin'` 账号；违反返回 `409 LAST_ADMIN_PROTECTED`
- 连续失败自动禁用：见 5.3 的熔断规则

**异常处理**

| 情况 | 用户看到 |
|------|---------|
| 连通性测试超时 | "测试失败：连接超时（15s），检查 base_url 或服务器出网" |
| 401/403 | "鉴权失败：API Key 无效或已过期" |
| 404 | "路径错误：该 base_url 下没有 /models 或 /chat/completions" |
| 停用最后一个渠道 | 弹窗二次确认："停用后 smart / fast 两个模型将不可用，影响 3 个房间，确认？" |

**数据流向**：`POST /api/admin/channels` → `ChannelService.create` → 加密 Key → 写 `channels` + `model_channels` → 写 `audit_logs` → 清 Redis 路由缓存。

### 5.2.1 协议适配矩阵（通用接入的核心）

三种协议的差异全部封装在各自适配器内，上层（路由、配额、流式转发、结算）完全不感知。

| 维度 | openai_compatible | anthropic | gemini |
|------|-------------------|-----------|--------|
| 对话端点 | `POST {base}/chat/completions` | `POST {base}/v1/messages` | `POST {base}/v1beta/models/{model}:streamGenerateContent?alt=sse` |
| 模型列表 | `GET {base}/models` → `data[].id` | `GET {base}/v1/models` → `data[].id` | `GET {base}/v1beta/models` → `models[].name`（需剥离 `models/` 前缀） |
| 鉴权头 | `Authorization: Bearer <key>` | `x-api-key: <key>` + `anthropic-version: 2023-06-01` | `x-goog-api-key: <key>`（**禁用 `?key=` query 方式**，会进访问日志） |
| 系统提示词 | `messages` 内 `role: system` | **顶层 `system` 字符串**，不在 messages 内 | 顶层 `systemInstruction.parts[].text` |
| 消息角色 | `system` / `user` / `assistant` | `user` / `assistant` | `user` / **`model`**（不是 assistant） |
| 消息内容 | `content` 字符串 | `content` 字符串或 blocks 数组 | `parts: [{text}]` 数组 |
| 必填差异 | `max_tokens` 可选 | **`max_tokens` 必填** | `generationConfig.maxOutputTokens` 可选 |
| 参数位置 | 请求体顶层 | 请求体顶层 | 嵌在 `generationConfig` 内 |
| 流式分片取值 | `choices[0].delta.content` | `content_block_delta` 事件的 `delta.text` | `candidates[0].content.parts[0].text` |
| 流式终止标记 | `data: [DONE]` | `event: message_stop`（**无 [DONE]**） | **无终止标记**，靠连接关闭判定 |
| SSE 事件形态 | 仅 `data:` 行 | `event:` + `data:` 两行配对 | 仅 `data:` 行 |
| 输入 token | `usage.prompt_tokens` | `message_start` 的 `message.usage.input_tokens` | `usageMetadata.promptTokenCount` |
| 输出 token | `usage.completion_tokens`；**流式必须请求带 `stream_options.include_usage=true`，否则拿不到 usage** | `message_delta` 的 `usage.output_tokens` | `usageMetadata.candidatesTokenCount` |
| 正常结束 | `finish_reason: stop` | `stop_reason: end_turn` | `finishReason: STOP` |
| 长度截断 | `finish_reason: length` | `stop_reason: max_tokens` | `finishReason: MAX_TOKENS` |
| 内容拦截 | `finish_reason: content_filter` | 无专用值，看 `stop_reason` 与错误体 | `finishReason: SAFETY` / `RECITATION` |
| 参数白名单默认值 | `temperature, top_p, max_tokens, stream, stop` | `temperature, top_p, max_tokens, stream, stop_sequences` | `temperature, topP, maxOutputTokens, stopSequences` |
| 401/403 常见原因 | Bearer 无效 | x-api-key 无效或缺 version 头 | Key 无效或未开通该模型 |
| 429 行为 | RPM/TPM 限流 | 同左，看 `retry-after` | 同左，免费层限流更严 |

**适配器统一契约**（`adapter/base.py`，三个适配器各自实现）

```python
class ProtocolAdapter(ABC):
    protocol: ClassVar[str]                    # openai_compatible / anthropic / gemini
    default_params: ClassVar[list[str]]        # 参数白名单默认值
    @abstractmethod
    async def stream_chat(self, req: UnifiedRequest) -> AsyncIterator[StreamEvent]: ...
    @abstractmethod
    async def test_connectivity(self) -> TestResult: ...   # 最小请求，返回延迟与错误分类
    @abstractmethod
    async def list_models(self) -> list[str]: ...          # 供「同步模型列表」使用
    @abstractmethod
    def build_headers(self, key: str) -> dict: ...
    @abstractmethod
    def normalize_error(self, status: int, body: dict) -> UpstreamError: ...
```

`UnifiedRequest` 是内部统一结构（OpenAI 风格），各适配器负责翻译成目标协议；`StreamEvent` 统一为 `meta / delta / usage / done / error` 五类，与 8.7 定义的 SSE 事件一一对应。**上层只认 UnifiedRequest 与 StreamEvent，永不接触厂商字段。**

**厂商预设**（`adapter/presets.py`，一键填充 base_url 与默认超时）

| 协议 | 预设 |
|------|------|
| openai_compatible | OpenAI、DeepSeek、阿里百炼、SiliconFlow、OpenRouter、Groq、Moonshot、智谱、Together、Ollama（本地）、vLLM（自建） |
| anthropic | Anthropic 官方、兼容代理（自填 base_url） |
| gemini | Google AI Studio（API Key 模式） |

> 预设的 base_url 是便利值，**实现时必须逐个用「测试连通性」验证**；上游改版只需改预设表，不动适配器逻辑。
> **V1 不支持 Vertex AI**（OAuth 鉴权与 URL 结构均不同），列入 V2。`custom` 类型预留给第四种协议，V1 界面不可选。

### 5.3 渠道路由与容错（核心）

**选路算法**（每次 AI 调用执行一次）

```python
def select_channel(model_public_name: str) -> Channel:
    # 1. 缓存优先（Redis: route:{model} TTL 60s，渠道变更时主动失效）
    candidates = cache.get(f"route:{model_public_name}")
    if candidates is None:
        candidates = db.query("""
            SELECT c.*, mc.upstream_model
            FROM model_channels mc
            JOIN channels c ON c.id = mc.channel_id
            JOIN models   m ON m.id = mc.model_id
            WHERE m.public_name = :name AND m.enabled AND mc.enabled
              AND c.status = 'enabled'
              AND (c.cooldown_until IS NULL OR c.cooldown_until < now())
            ORDER BY c.priority DESC, c.weight DESC
        """, name=model_public_name)
        cache.set(f"route:{model_public_name}", candidates, ttl=60)
    if not candidates:
        raise NoChannelAvailable(model_public_name)

    # 2. 取最高优先级档，档内按权重加权随机
    top = max(c.priority for c in candidates)
    pool = [c for c in candidates if c.priority == top]
    return weighted_random(pool)          # P(c) = c.weight / sum(weights)
```

**三级容错**

| 级别 | 触发 | 行为 |
|------|------|------|
| L1 同渠道重试 | 网络抖动、5xx、超时 | 指数退避 1s / 2s，最多 2 次；**仅幂等的调用重试**（流式已吐出内容后不重试） |
| L2 跨渠道 fallback | 该渠道最终失败 | `fail_count += 1`，写 `cooldown_until = now() + 60s`，重新选路下一个渠道，最多换 2 个渠道 |
| L3 自动禁用 | `fail_count >= 3` 且非配额类错误 | `status = 'auto_disabled'`，写审计，推送管理员；后台健康巡检恢复 |

**关键区分**：上游返回 429（限流）→ 走 L2 换渠道；返回 401/403（鉴权）→ 直接 L3 禁用该渠道，不重试；返回 400（参数不支持）→ 不重试、不禁用，记录 `fail_reason=unsupported_param`，提示管理员补充参数白名单。

**健康巡检**（scheduler，每 5 分钟）：对 `status IN ('enabled','auto_disabled')` 的渠道发最小请求；成功则 `fail_count=0`，若原为 `auto_disabled` 则恢复 `enabled` 并写审计。

### 5.4 单聊会话

**功能描述**：用户创建会话、绑定模型、多轮对话、SSE 流式输出。

**业务规则**

- 一个会话绑定一个模型，切换模型只影响后续消息，历史不清空、上下文不串
- 上下文组装：系统提示词 + 最近 N 条消息，N 由 `context_window`（默认 20）与 token 上限（默认 8k）双约束，超限按时间从旧到新截断，**系统提示词永不截断**
- 会话标题：首条用户消息前 20 字；用户可重命名
- 软删除：`DELETE /api/conversations/{id}` 物理删除该会话及其消息（V1 不做回收站），需二次确认
- **草稿只存前端 localStorage**（`draft:{convId}`），数据库不存草稿内容；消息列表的「[草稿]」红字由前端按本地是否有草稿渲染，`GET /api/conversations` 不返回草稿字段
- **「联网」开关 V1 隐藏**：`feature_flags.web_search=false`，前端按 flag 决定是否渲染该 chip（原型上保留是为展示 V2 形态）

**异常处理**

| 情况 | 用户看到 |
|------|---------|
| 无可用渠道 | "该模型暂不可用，请切换模型或联系管理员" |
| 配额用尽 | "今日消息已达上限（50/50），明日 00:00 恢复" |
| 首字超时（15s） | 气泡显示"响应超时"，保留已收内容，提供"重试"按钮，预扣已退回 |
| 整体超时（60s） | 同上，`status='timeout'` |
| 命中敏感词（输入侧） | "内容不符合规范，请修改后重试"，不展示命中词，不调模型、不扣配额 |
| 命中敏感词（输出侧） | 已流式吐出的内容替换为"该回复因内容安全策略被拦截"，`status='blocked'`，按已产生 token 结算 |

**数据流向**：`POST /api/conversations/{id}/messages`（SSE）→ 敏感词过滤 → `QuotaService.freeze` → `RouterService.select_channel` → `AdapterService.stream_chat` → 逐 chunk 通过 SSE 下发 + Redis 发布 → 结束 `QuotaService.settle` → 写 `messages` + `usage_logs` + 更新 `daily_usage` + `conversations.last_message_at`。

**幂等性**：客户端生成 `Idempotency-Key`（UUID）随请求发送；`messages.idempotency_key` 唯一索引兜底；同键重复提交返回首次结果而不重复调用模型。

**会话级串行与竞态防护（必须实现）**

- 同一会话同时只允许 1 个进行中的 AI 请求：`UPDATE conversations SET active_call_id = :call_id WHERE id = :id AND active_call_id IS NULL RETURNING id`，返回空即已有请求在跑 → 响应 `409 AI_IN_PROGRESS` 并附带进行中的 `call_id`，前端可续接该流
- 结束（done / error / 客户端断开）时在 `finally` 中清空：`UPDATE conversations SET active_call_id = NULL WHERE id = :id AND active_call_id = :call_id`（带 call_id 条件，避免误清后来者）
- **generation_id 防覆盖**：用户点「重新生成」时前端生成新的 `generation_id`；服务端在落库前校验它是否为该会话最新代次，旧代的流即使后到也**只丢弃不落库**，杜绝"旧回复覆盖新回复"
- 「重新生成」与「追问」同受 5s 冷却限制（与房间 @AI 一致），防止反复点击烧配额

### 5.5 房间与群聊

**功能描述**：创建房间、准入控制、成员管理、多人发言、@AI 触发。

**业务规则**

- 准入：`public`（任何人可进）/ `invite_code`（需房间邀请码）/ `approval`（需房主或管理员审批）
- 满员：`member_count >= max_members` 时拒绝加入，可进 `room_join_requests` 排队（V1 简化为直接提示已满，排队列入 V2）
- 发言限流：单成员 1 条 / 2 秒、20 条 / 分钟（Redis 滑动窗口）；当日发言上限 200 条
- 禁言：`room_members.muted_until`；敏感词连续命中 3 次自动禁言 10 分钟
- AI 触发：默认 `mention`（仅 @AI 触发）；`every` 模式下每条消息都触发（房主需显式开启，且强制受预算约束）
- **房间级串行**：同一房间同时最多 1 个 AI 请求在执行（Redis `SET room:{id}:ai_lock {call_id} NX PX 120000`）；抢锁失败时返回排队位次（`LLEN room:{id}:ai_queue`），**排队阶段不预扣**
- 消息广播：写库成功后 `PUBLISH room:{id} {message_json}`，所有订阅该频道的 WebSocket 连接收到并渲染；发送者自己走本地回显避免重复
- 在线状态：Redis `ZADD room:{id}:online {now_ts} {user_id}`，心跳 30s，读取时按 90s 内活跃过滤

**异常处理**

| 情况 | 用户看到 |
|------|---------|
| 房间已满 | "房间已满 50/50" |
| 需邀请码 | 输入框 + "向房主申请"按钮 |
| 被禁言 | 输入框禁用 + "禁言至 08:30" |
| 房间 AI 熔断 | 系统消息"今日房间 AI 额度已用完，明日 00:00 恢复"，@AI 按钮置灰并说明原因 |
| @AI 排队 | "已排队，前面还有 N 条"，可取消 |
| WebSocket 断连 | 顶部提示"连接中…"，指数退避重连（1s/2s/4s/8s/16s，最多 5 次），重连后按 `last_msg_id` 增量补齐 |
| 房主被封禁 | 房间 `ai_status='closed'`，成员看到"房间 AI 已停用"，仍可发言 |

**数据流向**：
- 发言：`WS /ws/rooms/{id}` 或 `POST /api/rooms/{id}/messages` → 限流 → 敏感词 → 写 `messages` → `PUBLISH` → 更新在线与未读
- @AI：`POST /api/rooms/{id}/ai/ask`（SSE）→ 四连校验 → 抢房间锁 → 预扣（归属房主）→ 路由 → 流式（同时 PUBLISH 给全房间）→ 结算 → 释放锁 → 熔断判定

**并发控制**：
- `rooms.member_count` 用条件 UPDATE 保证不超员：`UPDATE rooms SET member_count = member_count + 1 WHERE id = :id AND member_count < max_members RETURNING member_count`，返回空即满员
- 房间 AI 串行靠 Redis 锁，锁必须带 TTL（120s）防止持有者崩溃导致永久阻塞；释放时用 Lua 脚本校验 `call_id` 一致，避免误删他人锁

### 5.6 配额、结算与熔断（核心）

#### 5.6.1 四连校验顺序（不可调换）

```
① 登录态与账号状态 → ② 房间 AI 状态 → ③ 冷却与串行队列 → ④ 配额余量
```
把配额校验放最后，是因为它要做原子写操作，前面的轻量校验先挡掉大部分无效请求，减少数据库压力。

#### 5.6.2 预扣（freeze）

```sql
-- 冻结量 = 实际 prompt tokens + max_output_tokens
INSERT INTO daily_usage (quota_date, owner_id, room_id, total_tokens, ai_call_count)
VALUES (:d, :owner, :room, :freeze, 1)
ON CONFLICT (quota_date, owner_id, room_id)
DO UPDATE SET
  total_tokens  = daily_usage.total_tokens  + EXCLUDED.total_tokens,
  ai_call_count = daily_usage.ai_call_count + 1
WHERE daily_usage.total_tokens + EXCLUDED.total_tokens <= :limit
RETURNING total_tokens;
```

- **返回空结果集 = 超限**，直接拒绝，`usage_logs.status='failed'`，`fail_reason='quota_exceeded'`
- 单条语句 + WHERE 条件，天然原子，无需显式事务锁
- 房间预算与用户配额各执行一次上述语句（`room_id` 分别为房间 ID 和 NULL），**两次都成功才放行**；第二次失败要回滚第一次（同事务内即可）
- 同时写 `usage_logs(status='pending', frozen_tokens=:freeze)`，并把 `call_id` 透传给后续所有环节

#### 5.6.3 结算（settle）

```sql
UPDATE daily_usage
SET total_tokens      = total_tokens      - :frozen + :actual,
    prompt_tokens     = prompt_tokens     + :prompt,
    completion_tokens = completion_tokens + :completion,
    cost              = cost              + :cost,
    updated_at        = now()
WHERE quota_date = :d AND owner_id = :owner AND room_id IS NOT DISTINCT FROM :room;

UPDATE usage_logs
SET status = 'settled', prompt_tokens = :prompt, completion_tokens = :completion,
    total_tokens = :actual, cost = :cost, first_token_ms = :ftt, total_ms = :total,
    settled_at = now()
WHERE call_id = :call_id AND status = 'pending';
```

`cost = prompt_tokens / 1e6 * price_input + completion_tokens / 1e6 * price_output`（按 `models` 表单价，保留 6 位小数）。

#### 5.6.4 退回（refund）

超时、上游报错、用户取消、内容拦截未产生输出时：

```sql
UPDATE daily_usage SET total_tokens = GREATEST(total_tokens - :frozen, 0),
       ai_call_count = GREATEST(ai_call_count - 1, 0), updated_at = now()
WHERE quota_date = :d AND owner_id = :owner AND room_id IS NOT DISTINCT FROM :room;

UPDATE usage_logs SET status = 'refunded', fail_reason = :reason, settled_at = now()
WHERE call_id = :call_id AND status = 'pending';
```

**悬挂兜底**：scheduler 每 10 分钟扫描 `status='pending' AND created_at < now() - interval '10 minutes'` 的记录，一律按 refund 处理并写审计——这是防止进程崩溃导致额度永久冻结的最后防线。

#### 5.6.5 熔断判定与状态机

结算后立即执行：

```python
ratio = room_used_tokens / room.daily_token_budget
if ratio >= 1.0:   transition(room, 'suspended')
elif ratio >= 0.8: transition(room, 'warning')
elif room.ai_status in ('warning',) and ratio < 0.8: transition(room, 'normal')
```

| 当前态 | 触发 | 目标态 | 副作用 |
|--------|------|--------|--------|
| normal | ratio ≥ 0.8 | warning | 房间顶部黄条；推送房主 |
| warning | ratio ≥ 1.0 | suspended | 广播系统消息；@AI 置灰；推送房主；写审计 |
| warning | 房主提额致 ratio < 0.8 | normal | 撤黄条 |
| suspended | 日切（Asia/Shanghai 00:00） | normal | 广播"额度已恢复" |
| suspended | 房主提额 / 换更便宜模型 | normal | 同上 |
| any | 房主关闭 AI / 绑定模型被停用 / 房主被封 | closed | 输入框隐藏 @AI |
| closed | 房主重开且模型可用 | normal | — |

**双闸门**：房间预算与房主用户级日配额独立累加，**取先到者**触发熔断。房主自己单聊也消耗用户级配额。

**Redis 与 DB 的关系**：Redis 存 `quota:{owner}:{date}` 与 `quota:room:{room}:{date}` 计数器（TTL 到次日 00:05）做热路径快速判定；`daily_usage` 表是真相源。Redis 数据丢失时由 scheduler 从 `daily_usage` 重算回填。

### 5.7 用量统计（管理员）

- 三维度聚合：按用户 / 按房间 / 按模型，数据源统一为 `daily_usage` + `usage_logs`
- 时间范围：今日 / 近 7 日 / 近 30 日；`quota_date` 已按 Asia/Shanghai 落库，聚合无需再做时区转换
- 告警：房间预算 ≥ 80% 生成告警卡；用户当日触发限额 ≥ 3 次生成告警卡
- 导出：CSV，最多 1 万行，超出走异步任务（BackgroundTasks）并在完成后站内通知
- 缓存：概览接口结果缓存 Redis 60s（统计非实时敏感）

### 5.8 内容安全

- 输入侧：发送前过滤，命中即拒绝（不入房间、不调模型、不扣配额），写审计（含命中词分类，不含原文全文，原文只存哈希）
- 输出侧：流式内容按句缓冲检测，命中则中断流并替换提示语，按已产生 token 结算
- 词库：本地词库文件 + DFA 算法（V1 不接第三方审核 API，成本考虑）；词库版本号存 `settings.moderation.wordlist_version`，更新后热加载
- 连续命中 3 次自动禁言 10 分钟（房间）或锁定 15 分钟（单聊）

---

## 6. AI Prompt 设计

### 6.1 房间系统提示词模板

```
你是「{room_name}」房间里的 AI 助手。

房间主题与规则：
{room_system_prompt}

行为约束：
1. 你只在被 @AI 明确提及时回答，不要主动插话。
2. 房间里有多名成员，回答时面向全体，不要只回应最后一个人。
3. 若成员之间已给出正确答案，简短确认即可，不要重复长篇输出。
4. 回答保持简洁：默认不超过 300 字，除非被明确要求展开。
5. 涉及代码时用代码块；涉及翻译时直接给译文，不要解释过程。
6. 不知道就直说不知道，不要编造事实、数字、引用或链接。

当前上下文说明：以下是房间最近的对话记录，发言人姓名在每条消息前标注。
```

**输入变量**：`room_name`（房间名）、`room_system_prompt`（房主自定义，可为空，为空时替换为"这是一个多人讨论房间，请按成员请求提供帮助"）

**Token 控制**：系统提示词固定约 300 token；上下文按 `context_window`（默认 20 条）与 8k token 双约束截断；`max_tokens` 默认取 `models.max_output_tokens` 与 2048 的较小值。

### 6.2 单聊默认系统提示词

```
你是一位简洁、专业、可靠的 AI 助理。
- 直接给结论，再按需展开，不使用"好问题""我很乐意帮忙"这类客套开场。
- 不确定就明说不确定，不编造事实、数字、引用或链接。
- 用户用中文提问时用中文回答；代码、命令、专有名词保留原文。
- 涉及医疗、法律、投资等专业领域时给出信息而非结论，并提示咨询专业人士。
{user_system_prompt}
```

`user_system_prompt` 为会话级"人设"，用户在会话设置里自定义，可为空。

### 6.3 输出格式与容错

本项目 AI 输出为**自由文本流式**，不要求 JSON 结构，因此不存在 JSON 解析失败问题。需要容错的是：

| 异常 | 处理 |
|------|------|
| 上游返回空内容 | 提示"模型返回为空，请重试"，`status='failed'`，全额退回 |
| 流中途断开 | 保留已收内容，`status='timeout'`，按已产生 token 结算，提示可追问继续 |
| 上游返回 `finish_reason='length'` | 正常落库，前端在气泡下方显示"已达长度上限，可点继续" |
| 上游返回 `finish_reason='content_filter'` | `status='blocked'`，提示"该回复被上游内容策略拦截"，退回预扣 |
| usage 字段缺失 | 用 tiktoken 本地估算 completion tokens，`usage_logs.fail_reason='usage_missing_estimated'` 标记，成本按估算值计 |

**Fallback**：所有模型不可用时，前端展示"AI 服务暂时不可用，成员之间仍可正常交流"，房间聊天功能不受影响。

---

## 7. 页面清单与路由

### 7.1 移动端 H5（成员，按原型 v6）

| 页面 | 路由 | 说明 | 权限 |
|------|------|------|------|
| 登录 / 注册 | `/login` | 深色品牌页，tab 切换，注册含邀请码 | 公开 |
| 消息（首页） | `/msgs` | 会话列表：置顶、免打扰、草稿、未读、房间聚合、系统通知 | 登录 |
| 列表（房间广场） | `/rooms` | 分类芯片 + 房间卡（在线数/成员/绑定模型/最后消息/进入按钮） | 登录 |
| 我的 | `/me` | 用户卡、今日用量三条进度、管理入口、偏好设置、退出 | 登录 |
| 单聊详情 | `/c/:convId` | 工具条（模型/人设/联网/余量）+ 消息流 + 输入区 | 登录且属主 |
| 房间详情 | `/r/:roomId` | 房间主题条 + 在线成员条 + 多人消息流 + @AI 输入区 | 登录且成员 |

### 7.2 管理后台（管理员，**桌面与移动端均为完整功能**）

同一套页面、两种布局形态，功能不分级：

- **移动端（<768px）**：卡片式列表 + 底部抽屉式编辑，即原型 v6「控制台 / 用量统计」页的形态。全部 CRUD 都能在手机上完成，不做只读阉割
- **桌面端（≥1024px）**：左侧固定导航 + 右侧内容双栏；列表改表格（可排序、可批量选择），编辑改右侧抽屉或模态框，统计图表并排
- **断点规则**：`<768px` 卡片；`768-1023px` 卡片单栏居中（最大 720px）；`≥1024px` 表格双栏
- **表格降级**：权限矩阵、调用流水等多列数据在 `<768px` 转为「卡片 + 键值对」或横向滚动容器（首列固定），禁止直接挤压列宽

| 页面 | 路由 | 说明 |
|------|------|------|
| 控制台首页 | `/admin` | 概览卡片 + 告警 + 快捷入口 |
| 渠道管理 | `/admin/channels` | 渠道列表、展开编辑、连通性测试、同步模型、启停 |
| 模型注册表 | `/admin/models` | 对外模型名、单价、上下文、绑定渠道、设默认 |
| 用户管理 | `/admin/users` | 列表、封禁、重置密码、单独配额覆盖 |
| 房间管理 | `/admin/rooms` | 列表、关闭 AI、归档、看房间用量 |
| 邀请码 | `/admin/invites` | 批量生成、使用情况、作废 |
| 用量统计 | `/admin/stats` | 时间范围切换、四维图表、调用流水、导出 |
| 系统设置 | `/admin/settings` | 全局配额、注册方式、内容安全、特性开关 |
| 审计日志 | `/admin/audit` | 按 action / actor / 时间检索 |

### 7.3 列表页规范

- 分页：游标分页（`cursor` + `limit`，默认 `limit=20`，最大 100），消息类列表一律游标而非 offset，避免翻页错位
- 排序：会话列表按 `pinned DESC, last_message_at DESC`；房间列表按分类 + `member_count DESC`；用量流水按 `created_at DESC`
- 搜索：会话与房间搜索走 `ILIKE` + 前缀索引，V1 不引入全文检索
- 空状态：每类列表必须有空态插画位 + 引导按钮（如"还没有会话，去新建一个"）

### 7.4 核心流程图

```
成员：登录 → /msgs → 点会话 → /c/:id → 发消息(SSE 流式) → 看回复 → 返回
成员：登录 → /rooms → 点房间 → /r/:id → 发言(WS 广播) → @AI(SSE) → 看 AI 回复 → 返回
房主：/rooms → 创建房间 → 设主题提示词/模型/预算/准入 → 邀请成员 → 收到预警推送 → 提额或换模型
管理员：/admin/channels → 添加渠道 → 测试连通 → 同步模型 → 绑定到对外模型名 → 启用
       → /admin/stats → 看四维用量 → 处理告警 → /admin/settings 调限额
```

### 7.5 弱网与离线兜底

| 场景 | 方案 |
|------|------|
| 输入长文本时断网 | localStorage 自动暂存草稿（`draft:{convId}`），恢复后提示"有未发送的草稿" |
| 发送超时 | 自动重试 1 次（同 Idempotency-Key），仍失败保留输入内容并提示 |
| SSE 中断 | 前端按 `last_event_id` 重连一次；重连失败则提示"连接中断，回复可能不完整"，并允许点"刷新获取完整回复"（从 DB 读最终态） |
| WebSocket 断连 | 指数退避重连 + 顶部"连接中…"提示 + 重连后增量补齐 |
| 弱网重复点击 | 发送按钮进入 loading 禁用态，直到收到首个 SSE 事件或超时 |

---

## 8. API 接口清单

统一前缀 `/api`；除 `auth` 与 `health` 外全部需要 `Authorization: Bearer <token>`。
统一响应包装：成功 `{"code":0,"data":{...},"trace_id":"..."}`；失败 `{"code":"ERROR_NAME","message":"用户可读文案","detail":{...},"trace_id":"..."}`。
所有响应头返回 `X-Request-ID`（即 trace_id）。

### 8.1 认证（6）

| 方法 | 路径 | 说明 | 角色 |
|------|------|------|------|
| POST | `/api/auth/register` | 注册 | 公开 |
| POST | `/api/auth/login` | 登录 | 公开 |
| POST | `/api/auth/logout` | 登出（jti 入黑名单） | 登录 |
| GET | `/api/auth/me` | 当前用户信息 + 今日配额 | 登录 |
| POST | `/api/auth/password` | 修改自己密码 | 登录 |
| GET | `/api/health` | 健康检查（含 db/redis 状态） | 公开 |

### 8.2 模型（1）

| GET | `/api/models` | 当前用户可见的已启用模型列表 | 登录 |

### 8.3 单聊会话（8）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/conversations` | 会话列表（含最后一条摘要、未读、置顶、草稿标记） |
| POST | `/api/conversations` | 新建会话（可指定 model_id、system_prompt） |
| GET | `/api/conversations/{id}` | 会话详情 |
| PATCH | `/api/conversations/{id}` | 改标题/置顶/免打扰/模型/人设 |
| DELETE | `/api/conversations/{id}` | 删除会话及其消息 |
| GET | `/api/conversations/{id}/messages` | 消息列表（游标分页） |
| POST | `/api/conversations/{id}/messages` | 发送用户消息（同步落库，返回 message_id） |
| POST | `/api/conversations/{id}/ai/completions` | **SSE**：触发 AI 流式回复 |

### 8.4 房间（17）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/rooms` | 房间广场列表（分类、搜索、分页） |
| POST | `/api/rooms` | 创建房间 |
| GET | `/api/rooms/{id}` | 房间详情（含 ai_status、预算用量比、我的角色） |
| PATCH | `/api/rooms/{id}` | 修改房间（房主/admin） |
| DELETE | `/api/rooms/{id}` | 归档房间（房主/admin） |
| POST | `/api/rooms/{id}/join` | 加入房间（含邀请码校验） |
| POST | `/api/rooms/{id}/leave` | 退出房间 |
| GET | `/api/rooms/{id}/members` | 成员列表 |
| PATCH | `/api/rooms/{id}/members/{uid}` | 改成员角色 / 解除禁言 |
| POST | `/api/rooms/{id}/members/{uid}/mute` | 禁言（含时长） |
| DELETE | `/api/rooms/{id}/members/{uid}` | 移出成员 |
| GET | `/api/rooms/{id}/requests` | 入房申请列表 |
| POST | `/api/rooms/{id}/requests/{rid}/decide` | 审批（approve/reject） |
| GET | `/api/rooms/{id}/messages` | 房间消息（游标分页，用于首屏与重连补齐） |
| POST | `/api/rooms/{id}/messages` | 发送房间消息（HTTP 兜底通道） |
| POST | `/api/rooms/{id}/ai/ask` | **SSE**：@AI 触发流式回复 |
| POST | `/api/rooms/{id}/ws-ticket` | 换取一次性 WebSocket 票据（TTL 60s，单次消费） |

WebSocket：`/ws/rooms/{id}?ticket=<一次性票据>`

**安全要求**：禁止把 JWT 放在 query string（会被 Caddy 访问日志、浏览器历史、Referer 记录）。改为：`POST /api/rooms/{id}/ws-ticket` 用 Bearer 认证换取一次性票据（Redis `ws_ticket:{ticket}` → `user_id`，TTL 60s，`GETDEL` 单次消费），前端拿票据建连，票据泄露也无法复用。

连接建立后：校验票据 → 校验房间成员身份 → `SUBSCRIBE room:{id}` → 客户端每 30s 发 `{"type":"ping"}`，服务端回 `{"type":"pong"}`，90s 无心跳则服务端主动关闭；重连时携带 `last_msg_id`，服务端增量补发。

### 8.5 配额与通知（6）

| 方法 | 路径 | 说明 | 角色 |
|------|------|------|------|
| GET | `/api/quota/me` | 今日消息数/token/成本、重置倒计时、各房间预算状态 | 登录 |
| GET | `/api/unread-count` | 消息 tab 角标 = 会话未读 + 房间未读 + 通知未读（免打扰房间不计入） | 登录 |
| GET | `/api/notifications` | 通知列表（游标分页，可按 type / is_read 筛选） | 登录 |
| POST | `/api/notifications/{id}/read` | 单条标记已读 | 登录 |
| POST | `/api/notifications/read-all` | 全部标记已读 | 登录 |
| POST | `/api/rooms/{id}/read` | 上报房间已读位置 `last_read_msg_id`，用于未读计算 | 成员 |

### 8.6 管理端（30）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/admin/channels` | 渠道列表 / 新建 |
| GET/PATCH/DELETE | `/api/admin/channels/{id}` | 详情 / 修改 / 删除 |
| POST | `/api/admin/channels/{id}/test` | 连通性测试 |
| POST | `/api/admin/channels/{id}/sync-models` | 同步上游模型列表 |
| POST | `/api/admin/channels/{id}/toggle` | 启用 / 停用 |
| GET/POST | `/api/admin/models` | 模型注册表列表 / 新建 |
| PATCH/DELETE | `/api/admin/models/{id}` | 修改 / 删除 |
| POST | `/api/admin/models/{id}/default` | 设为默认模型 |
| POST | `/api/admin/models/{id}/channels` | 绑定渠道（含 upstream_model） |
| GET | `/api/admin/users` | 用户列表 |
| PATCH | `/api/admin/users/{id}` | 改配额 / 角色 |
| POST | `/api/admin/users/{id}/ban` | 封禁 / 解封 |
| POST | `/api/admin/users/{id}/reset-password` | 重置密码 |
| GET/POST/DELETE | `/api/admin/invite-codes` | 邀请码管理（POST 支持批量生成） |
| GET | `/api/admin/rooms` | 全部房间（含 AI 状态） |
| PATCH | `/api/admin/rooms/{id}` | 强制关闭 AI / 归档 |
| GET | `/api/admin/stats/overview` | 概览指标 |
| GET | `/api/admin/stats/timeseries` | 趋势（按日） |
| GET | `/api/admin/stats/breakdown` | 按用户/房间/模型维度 |
| GET | `/api/admin/usage-logs` | 调用流水（筛选 + 分页） |
| GET/PUT | `/api/admin/settings` | 系统设置读写 |
| GET | `/api/admin/audit-logs` | 审计日志检索 |

**API 总数：69 个（68 个 REST 端点 + 1 个 WebSocket 端点）**

构成：认证 6 + 模型 1 + 单聊会话 8 + 房间 17（含 ws-ticket）+ 配额与通知 6 + 管理端 30 + WebSocket 1 = 69。
> 管理端表格中 `GET/POST`、`GET/PATCH/DELETE`、`GET/POST/DELETE` 等合并行按方法数分别计数。

### 8.7 关键 Schema 定义

#### POST /api/auth/register

请求体：

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| email | string(email) | 与 phone 二选一 | RFC5322，最长 254 |
| phone | string | 与 email 二选一 | `^\+?[0-9]{7,15}$` |
| password | string | 是 | 8-72 位，须含字母与数字 |
| nickname | string | 是 | 1-32 位，去除首尾空白 |
| invite_code | string | 注册方式为 invite_code 时必填 | 最长 24 |
| idempotency_key | string(uuid) | 否 | 客户端生成，10 分钟内幂等 |

```json
{
  "email": "xiaowan@example.com",
  "password": "Passw0rd2026",
  "nickname": "小 Wan",
  "invite_code": "RM-8F3K2A",
  "idempotency_key": "6f1c1a3e-9b7d-4c2e-8a51-2f6d0c9b4e17"
}
```

响应 `200`：

```json
{
  "code": 0,
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "expires_at": "2026-11-18T09:55:00Z",
    "user": {
      "id": 42, "nickname": "小 Wan", "email": "x***n@example.com",
      "role": "member", "daily_msg_limit": 50, "daily_token_limit": 100000
    }
  },
  "trace_id": "9c1f0a6e-2b7d-4e31-9a55-7d2c8b41f0e3"
}
```

失败 `422`：

```json
{"code":"INVITE_CODE_INVALID","message":"邀请码无效或已被使用",
 "detail":{"field":"invite_code"},"trace_id":"9c1f0a6e-..."}
```

#### POST /api/auth/login

请求：`{"email":"xiaowan@example.com","password":"Passw0rd2026"}`
响应结构同注册。失败：`401 AUTH_FAILED`「邮箱或密码错误」；`423 ACCOUNT_LOCKED`「尝试过于频繁，请 15 分钟后重试」；`403 ACCOUNT_BANNED`。

#### POST /api/rooms/{id}/ai/ask（SSE）

请求体：

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| content | string | 是 | 1-4000 字，须含 `@AI` 或房间为 `every` 模式 |
| reply_to_msg_id | integer | 否 | 必须属于本房间 |
| idempotency_key | string(uuid) | 是 | 防重复提交 |

响应 `Content-Type: text/event-stream`，事件序列：

```
event: meta
data: {"call_id":"b7e2...","model":"smart","channel_id":3,"queue_pos":0}

event: delta
data: {"content":"译文"}

event: delta
data: {"content":"：本条款"}

event: usage
data: {"prompt_tokens":312,"completion_tokens":96,"total_tokens":408,"cost":0.0021}

event: done
data: {"message_id":18432,"first_token_ms":820,"total_ms":6100,
       "room_budget_ratio":0.46,"room_ai_status":"normal"}

event: error
data: {"code":"AI_TIMEOUT","message":"响应超时，已退回本次额度","call_id":"b7e2...","refund":true}
```

错误码：`ROOM_AI_SUSPENDED`（熔断）、`ROOM_AI_CLOSED`、`QUOTA_EXCEEDED`、`COOLDOWN`、`QUEUED`（非错误，返回 `queue_pos`）、`NO_CHANNEL_AVAILABLE`、`CONTENT_BLOCKED`、`MUTED`、`AI_TIMEOUT`、`UPSTREAM_ERROR`。

#### POST /api/admin/channels

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 1-64 |
| type | enum | 是 | `openai_compatible` / `anthropic` / `gemini` / `custom` |
| base_url | string(url) | 是 | 不含末尾斜杠，如 `https://api.deepseek.com/v1` |
| api_key | string | 是 | 明文只在请求体出现一次，服务端加密后丢弃 |
| supported_params | string[] | 否 | 默认 `["temperature","top_p","max_tokens","stream"]` |
| weight | integer | 否 | 默认 100，0-1000 |
| priority | integer | 否 | 默认 0，越大越优先 |
| timeout_first_token_ms | integer | 否 | 默认 15000 |
| timeout_total_ms | integer | 否 | 默认 60000 |

响应只返回 `api_key_hint`（如 `****ab3d`），**不返回 api_key_enc，也不返回明文**。

#### GET /api/admin/stats/overview

```json
{"code":0,"data":{
  "range":"7d",
  "users_total":128,"users_new":6,"active_today":36,
  "messages_total":8412,"ai_calls_total":1203,
  "tokens_total":934000,"cost_total":17.60,"currency":"CNY",
  "delta":{"messages":0.182,"cost":-0.043,"active":0.125},
  "alerts":[{"type":"room_budget","room_id":7,"room_name":"代码室","ratio":0.78},
            {"type":"user_limit","user_id":31,"nickname":"老周","hits":3}],
  "first_token_p95_ms":1180
},"trace_id":"..."}
```

### 8.8 超时与幂等标注

| 接口类型 | 预期响应 | 超时阈值 | 幂等 |
|---------|---------|---------|------|
| 普通读写 API | < 200ms | 3s | GET 天然幂等 |
| 登录 / 注册 | < 400ms（argon2 有意慢） | 10s | Idempotency-Key |
| 发消息（落库） | < 150ms | 3s | Idempotency-Key + 唯一索引 |
| SSE AI 调用 | 首字 < 1.5s，总 < 60s | 首字 15s / 总 60s | Idempotency-Key（重放返回首次 call_id） |
| 连通性测试 | < 5s | 15s | 天然幂等 |
| 统计聚合 | < 800ms | 5s | 天然幂等 |
| CSV 导出 | 异步 | 5min | 同参数 10 分钟内复用结果 |

---

## 9. 高并发与性能方案

### 9.1 峰值流量估算

无集中触发时间点（不是抢票/秒杀类），按常规公式：

```
峰值 QPS ≈ 日活 × 人均日请求数 / 86400 × 峰值系数
        = 30   × 120            / 86400 × 5
        ≈ 0.21 QPS（平均业务请求）
```

但这个数字没有意义，真正的约束是**长连接数**与**AI 并发数**：

```
同时在线 ≈ 日活 × 25% = 8 人（V1 设计目标 20 人）
WebSocket 长连接 ≈ 在线人数 × 打开的房间数 ≈ 20 × 1.5 = 30 条
AI 并发 ≈ 在线人数 × 5% = 1 条（房间级串行进一步压低到每房间 ≤ 1 条）
消息写入峰值 ≈ 20 人 × 0.2 条/秒 = 4 TPS
```

**结论**：2核4G 单实例余量充足（PostgreSQL 单机可支撑数千 TPS 的简单写入）。真正的瓶颈是 AI 上游延迟（秒级），而这已经被房间级串行队列和配额闸门限制住了。

**必须追问的场景确认**：本产品无"所有人同一时刻做同一件事"的设计。若将来加入"定时活动房间"（如每晚 8 点集中答疑），需按全量到达重算：50 人 / 30 秒 ≈ 1.7 QPS 入房 + 50 条 WS 建连，仍在单机能力内。

### 9.2 并发承载分析

| 操作 | 同时人数 | 处理方式 | 目标响应 | 结论 |
|------|---------|---------|---------|------|
| 登录 | 20 | argon2id 有意慢（约 200ms CPU） | < 400ms | 2 核下 20 人并发登录会排队约 2s，可接受；若成为瓶颈改 `parallelism=2` |
| 发送房间消息 | 20 | 单条 INSERT + PUBLISH | < 150ms | 无压力 |
| @AI 调用 | 每房间 1（串行） | Redis 锁 + SSE | 首字 < 1.5s | 串行是设计选择，非瓶颈 |
| 配额扣减 | 20 | 单条条件 UPSERT | < 20ms | 行级锁竞争极小 |
| 统计页 | 1-2（仅管理员） | Redis 缓存 60s | < 800ms | 无压力 |
| WebSocket 保活 | 30 连接 | 30s 心跳 | — | 单进程可支撑数千连接 |

### 9.3 缓存策略

| 数据 | 位置 | TTL | 失效方式 |
|------|------|-----|---------|
| 路由候选渠道 | Redis `route:{model}` | 60s | 渠道/模型变更时主动 DEL |
| 模型注册表 | Redis `models:enabled` | 300s | 变更时主动 DEL |
| 系统设置 | 进程内 + Redis `settings:{key}` | 300s | 变更时主动 DEL |
| 统计概览 | Redis `stats:overview:{range}` | 60s | 自然过期 |
| 房间在线成员 | Redis ZSET `room:{id}:online` | 成员级 90s 判定 | 心跳刷新 |
| JWT 黑名单 | Redis `token_bl:{jti}` | = token 剩余有效期 | 自然过期 |

### 9.4 缓存防护

- **穿透**：不存在的 `room_id` / `model` 查询缓存空值 30s；管理端接口不做匿名缓存
- **击穿**：路由缓存重建用 Redis `SET NX` 互斥锁（`lock:route:{model}`，TTL 3s），未抢到锁的请求直接查库
- **雪崩**：所有 TTL 加 ±10% 随机偏移；Redis 不可用时降级为直查数据库（配额判定回落到 `daily_usage` 表，见 15.2）

### 9.5 异步任务配置

V1 **不引入 Celery**。任务分两类：

| 类型 | 实现 | 说明 |
|------|------|------|
| 请求内轻任务 | FastAPI `BackgroundTasks` | 发通知、写审计、清缓存；随请求生命周期，进程重启会丢，可接受 |
| 周期任务 | APScheduler（独立 scheduler 容器） | 见下表 |

| 任务 | 周期 | 超时 | 失败处理 |
|------|------|------|---------|
| 渠道健康巡检 | 5 分钟 | 30s | 记日志，下轮重试 |
| pending 用量兜底退回 | 10 分钟 | 60s | 告警 + 下轮重试 |
| 配额日切对账（Redis ↔ daily_usage） | 每日 00:05 | 5min | 告警，以 DB 为准回填 |
| 数据库备份 | 每日 03:00 | 30min | 告警 + 重试 1 次 |
| 消息归档 / 日志清理 | 每周日 04:00 | 30min | 告警 |
| 证书续期检查 | 每日 06:00 | 5min | 告警（Caddy 自身也会续期，双保险） |

**多实例注意**：scheduler 容器必须 `scale=1`；若将来多副本，所有任务需加 Redis 分布式锁。

### 9.6 数据库连接池

```python
create_async_engine(
    DATABASE_URL,
    pool_size=5,           # 每 worker 常驻；× workers 数才是总量，见下方精算
    max_overflow=5,        # 每 worker 峰值可扩到 10
    pool_pre_ping=True,    # 自动剔除断连
    pool_recycle=1800,     # 30 分钟回收，防 PG/中间件空闲断连
    pool_timeout=10,       # 取连接最多等 10s，超时抛错而非堆积
)
```
**连接数精算（易错点：连接池是每 worker 独立的）**

```
app:        uvicorn --workers 2 × (pool_size 5 + max_overflow 5) = 20
scheduler:  1 进程 × (pool_size 2 + max_overflow 2)              =  4
alembic:    迁移时临时                                            =  1
备份/psql:  运维手动                                              =  2
PG 保留:    superuser_reserved_connections                        =  3
──────────────────────────────────────────────────────────────────────
合计                                                            = 30  <  max_connections=100 ✓
```

因此 **`pool_size` 必须为 5、`max_overflow` 为 5**（不是 10+10），否则 2 个 worker 会吃掉 40 个连接。若将来把 `--workers` 提到 4，必须同步下调 pool 或上调 `max_connections`，并重算本表。

### 9.7 限流规则

| 维度 | 规则 | 实现 |
|------|------|------|
| 全局 IP | 120 req/min | Caddy 层 + 应用层双保险 |
| 登录 | 同账号 5 次/15min，同 IP 20 次/hour | Redis 计数 |
| 注册 | 同 IP 5 次/day | Redis 计数 |
| 房间发言 | 1 条/2s，20 条/min，200 条/day | Redis 滑动窗口 + daily_usage |
| 单聊发消息 | 2 条/3s，100 条/day | 同上 |
| @AI | 同用户同房间 ≥ 5s 间隔；房间级串行 | Redis 锁 + 时间戳 |
| 管理端写操作 | 30 req/min | Redis 计数 |

### 9.8 锁策略

| 场景 | 策略 |
|------|------|
| 配额扣减 | **无显式锁**，靠单条条件 UPSERT 的原子性（推荐，性能最好） |
| 房间 AI 串行 | Redis 分布式锁（`SET NX PX` + Lua 校验 call_id 释放） |
| 房间人数上限 | 条件 UPDATE + RETURNING，返回空即满员 |
| 邀请码核销 | 条件 UPDATE（`WHERE used_count < max_uses`）+ RETURNING |
| 渠道/模型配置修改 | 乐观锁 `updated_at` 比对，冲突返回 409 |
| 消息写入 | 无需锁（追加写） |

### 9.9 幂等性设计

| 接口 | 机制 |
|------|------|
| 注册、发消息、@AI | 客户端 `Idempotency-Key`（UUID）+ `messages.idempotency_key` 唯一索引；命中重复时返回首次结果 |
| 加入房间 | `room_members` 主键 `(room_id, user_id)` 唯一约束，重复加入返回 200 而非报错 |
| 审批入房 | 条件 UPDATE（`WHERE status='pending'`），影响行数 0 表示已处理 |
| 配额结算 / 退回 | 条件 UPDATE（`WHERE status='pending'`），重复调用无副作用 |
| 渠道启停 | 幂等（目标态相同直接返回成功） |

---

## 10. 安全设计

### 10.1 五层防护

**第一层 网络**

- Caddy 强制 HTTPS，HTTP → HTTPS 301；开启 HSTS（`max-age=31536000; includeSubDomains`）
- 安全响应头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: strict-origin-when-cross-origin`、`Content-Security-Policy: default-src 'self'; connect-src 'self' wss:; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com`
- 隐藏版本：Caddy 默认不暴露 server token
- 防火墙（ufw）：仅开放 22（改非默认端口）/ 80 / 443；**PostgreSQL 5432 与 Redis 6379 不对外**，仅 Docker 内网可达
- 上线前 DNS TTL 降到 300s，稳定后升回 3600s

**第二层 应用**

- JWT（HS256）+ Bearer Header，密钥 `JWT_SECRET` ≥ 32 字节随机，存 env
- RBAC：全局 `admin/member` + 房间级 `owner/manager/member`，每个接口显式声明所需权限（`Depends(require_admin)` / `room_perm`）
- SQL 注入：全量走 SQLAlchemy 参数化，禁止字符串拼接 SQL；`audit_logs.detail` 用 JSONB 参数绑定
- XSS：前端一律用 `{{ }}` 插值，**禁止 `v-html`**；AI 回复若需渲染 Markdown，用 `markdown-it` + `DOMPurify` 白名单过滤
- CSRF：JWT + Header 方式天然免疫；不使用 Cookie 存 token
- CORS：白名单 `["https://your-domain.com"]`，本地开发另配 `http://localhost:5173`；禁止 `*`
- 参数校验：所有入参 Pydantic v2 模型，禁止 `dict` 直传
- 文件上传（V1 关闭，`feature_flags.file_upload=false`）：启用时限制 MIME 白名单 + 大小 10MB + **校验文件头魔术字节**（不只看扩展名）+ UUID 重命名
- 生产环境关闭 Swagger：`docs_url=None, redoc_url=None, openapi_url=None`（由 env 控制）
- 登录锁定见 5.1
- 敏感操作二次确认见 3.5

**第三层 数据**

- 密码：argon2id（`time_cost=3, memory_cost=65536, parallelism=4`），不可逆
- **渠道 API Key：Fernet（AES-128-CBC + HMAC-SHA256）字段级加密**，密钥 `CHANNEL_CIPHER_KEY` 存 env，与 `JWT_SECRET` 分离；接口只返回末 4 位 hint
- 展示层脱敏：邮箱 `x***n@example.com`，手机 `138****5678`
- 数据库强密码（≥ 24 位随机），非默认端口可选
- 备份：每日 pg_dump → gzip → **gpg 加密** → 上传 R2/B2；保留 14 天日备 + 8 周周备
- 审计日志：见 10.4
- 消息内容默认保留 90 天（`settings.retention.days`，可配），到期由 scheduler 删除；用户可主动导出并删除自己的数据

**第四层 运维**

- SSH 仅密钥登录，禁密码，改非 22 端口；安装 fail2ban
- 容器以非 root 运行（Dockerfile 中 `USER app`）
- 基础镜像固定版本：`python:3.12-slim`（禁 `latest`），生产可固定 digest
- 依赖漏洞扫描：每月 `pip-audit` + `npm audit`；高危 24h 内评估、72h 内修复
- 错误响应不暴露堆栈：全局异常处理器统一转 `{"code":"INTERNAL","message":"服务器开小差了","trace_id":"..."}`，堆栈只进日志
- 服务器密码与 API Key 存密码管理器（1Password / Bitwarden），禁止存聊天记录

**第五层 证书与密钥生命周期**

- SSL：Caddy 自动续期；额外每日检查剩余天数，< 30 / 7 / 1 天各告警一次
- JWT 密钥轮换：支持 `JWT_SECRET` 与 `JWT_SECRET_PREV` 双密钥验证，旧密钥 24h 过渡期后移除
- 渠道 Key 轮换：管理端改 Key 即时生效，无需重启；支持同时保留新旧渠道做平滑切换（新渠道 priority 更高，旧的观察 1 天后停用）
- 数据库密码轮换：改密码 → 更新 `.env` → `docker compose up -d app scheduler`（连接池 `pool_pre_ping` 保证重连）
- `CHANNEL_CIPHER_KEY` 轮换需数据迁移：写一次性脚本用旧 Key 解密、新 Key 加密回写，全程备份先行

### 10.2 API 错误码

| HTTP | code 示例 | 前端处理 |
|------|----------|---------|
| 200 | — | 正常 |
| 400 | `BAD_REQUEST` | 显示字段错误 |
| 401 | `AUTH_FAILED` / `TOKEN_EXPIRED` | 清状态跳登录，带 redirect |
| 403 | `FORBIDDEN_ADMIN_ONLY` / `NOT_ROOM_MEMBER` / `ACCOUNT_BANNED` / `MUTED` | 提示无权限，不回显资源存在性 |
| 404 | `ROOM_NOT_FOUND` / `CONVERSATION_NOT_FOUND` | 提示未找到并返回列表 |
| 409 | `EMAIL_EXISTS` / `CONFLICT_STALE` | 提示冲突，建议刷新 |
| 422 | `INVITE_CODE_INVALID` / `VALIDATION_ERROR` | 逐字段提示 |
| 423 | `ACCOUNT_LOCKED` | 提示锁定剩余时间 |
| 429 | `RATE_LIMITED` / `COOLDOWN` / `QUEUED` | 节流 + 倒计时提示 |
| 500 | `INTERNAL` | 通用文案 + trace_id，不暴露堆栈 |
| 502 | `UPSTREAM_ERROR` | "模型服务异常，已退回本次额度" |
| 503 | `ROOM_AI_SUSPENDED` / `NO_CHANNEL_AVAILABLE` | 说明原因 + 恢复时间 |

### 10.3 日志规范

结构化 JSON（structlog），必含字段：

```json
{
  "timestamp": "2026-11-11T02:15:03.412Z",
  "level": "INFO",
  "trace_id": "9c1f0a6e-2b7d-4e31-9a55-7d2c8b41f0e3",
  "call_id": "b7e2c1d4-...",
  "user_id": 42,
  "room_id": 7,
  "action": "room.ai.ask",
  "duration_ms": 6100,
  "first_token_ms": 820,
  "status": "success",
  "ip": "203.0.113.7",
  "channel_id": 3,
  "model": "smart",
  "tokens": {"prompt": 312, "completion": 96},
  "cost": 0.0021,
  "error_detail": null
}
```

- **trace_id**：请求入口生成 UUID，贯穿 Service → DB → 上游调用；响应头 `X-Request-ID` 返回；用户报错时索取此码即可全链路定位
- **call_id**：一次 AI 调用的业务 ID，写入 `usage_logs`，前端错误提示中展示，便于对账
- **分级**：DEBUG（生产关闭）/ INFO（正常业务）/ WARN（重试、缓存未命中、配额 ≥80%）/ ERROR（调用失败、写库失败）/ CRITICAL（DB 断连、磁盘不足、安全事件）
- **禁止输出**：密码、JWT、API Key（含密文）、消息正文全文、身份证号
- **脱敏**：邮箱 `x***n@domain`、手机 `138****5678`、IP 保留（合规需要）
- **保留**：INFO 30 天，ERROR 90 天，CRITICAL 180 天；单文件 100MB 轮转，最多保留 20 个
- **必记事件**：登录成功/失败、权限被拒、渠道增删改与启停、模型绑定变更、用户封禁/解封/重置密码、邀请码生成、房间创建/归档/AI 状态变更、配额熔断触发、上游调用失败、定时任务执行结果

---

## 11. 移动端适配策略

- **断点**：`<768px` 移动端布局（底部三格 tab）；`768-1023px` 平板（同移动端，最大宽度 640px 居中）；`≥1024px` 桌面（左侧固定导航 + 右侧内容双栏，管理后台表格全宽）
- **设计稿基准**：375 × 812（原型 v6 即此尺寸），使用 `rem` + `clamp()` 做弹性字号
- **关键差异**：
  - 会话/房间详情：移动端输入框贴底并处理 `env(safe-area-inset-bottom)`；桌面端输入区固定高度 120px 可拉伸
  - 管理后台：**移动端提供完整 CRUD**，采用卡片列表 + 抽屉编辑（原型 v6 即此形态）；≥1024px 切表格 + 双栏。表格在 375 宽下一律降级为卡片或横向滚动（首列固定），不挤压列宽
  - 房间成员条：移动端横向滚动头像堆叠，桌面端展开为完整成员列表侧栏
- **浏览器兼容**：iOS Safari ≥ 15、Android Chrome ≥ 100、桌面 Chrome/Edge/Firefox 最近两个大版本
- **必须实测**：iOS Safari 的 `100dvh` 与键盘弹起时的布局跳动；SSE 在 iOS 后台切走时的断连恢复
- **不打包 App**（V1）：H5 + PWA manifest（可加桌面图标），不引入 Capacitor/uni-app

---

## 12. 开发规约与已知陷阱

> **本章是动手写代码前必读的踩坑预警。**

### 12.1 类型统一规约

- **时间**：数据库一律 `TIMESTAMPTZ`；Python 一律 **aware UTC**（`datetime.now(timezone.utc)`），禁止 `datetime.utcnow()`（已弃用且返回 naive）；前端展示时转本地时区
- **业务日期**：`quota_date` 是"配额日"，必须按 **Asia/Shanghai** 计算：`datetime.now(ZoneInfo("Asia/Shanghai")).date()`。服务器在 UTC 时区，直接用 `now().date()` 会导致配额在早上 8 点重置
- **主键**：全部 `BIGINT GENERATED ALWAYS AS IDENTITY`，禁止混用 UUID 主键；对外暴露的追踪标识用 UUID（`call_id`、`trace_id`、`idempotency_key`）
- **空值**：数据库 `NULL` = Python `None` = JSON `null`；前端表单空字符串在提交前转 `null`；**禁止用 `""` 或 `0` 表示"无"**
- **枚举**：全部小写字符串（`admin` / `member` / `pending` / `settled`），前后端一致；数据库用 `CHECK` 约束而非 PG enum 类型（enum 改值需 ALTER TYPE，迁移痛苦）
- **金额**：`NUMERIC(12,6)`，禁止 float；前端展示保留 2-4 位
- **token 数**：整型（INT / BIGINT），禁止浮点

### 12.2 框架组合兼容性

已知陷阱清单：

- `pytest-asyncio ≥ 1.0` 必须在 `pytest.ini` 显式设 `asyncio_mode = auto`，并注意 `asyncio_default_fixture_loop_scope` 默认为 function
- **SQLAlchemy 2.0 异步模式禁止 lazy loading**：所有关联查询显式 `selectinload()` / `joinedload()`，否则抛 `MissingGreenlet`
- Pydantic v2：`orm_mode` → `from_attributes`，`validator` → `field_validator`，`.dict()` → `.model_dump()`
- Alembic 异步需在 `env.py` 用 `connectable.run_sync(do_run_migrations)` 包装
- FastAPI 的 `BackgroundTasks` 在 SSE（`StreamingResponse`）中的执行时机是响应结束后，不要在流中途依赖它
- `openai` SDK v1.x 是全新 API（`client.chat.completions.create`），网上大量 v0.x 代码（`openai.ChatCompletion.create`）不兼容，**AI 生成代码时务必声明使用 v1.x 风格**
- Vue 3 的 `v-html` 与 CSP 冲突，且是 XSS 入口，禁用
- Caddy 反代 SSE 需 `flush_interval -1`；WebSocket 需自动处理 Upgrade（Caddy 2 默认支持，但要确认没有中间层缓冲）
- **模块级 engine / Redis 客户端会绑定首次使用时的 event loop**：pytest-asyncio 默认每测试函数一个新 loop，第二个测试起必报 `attached to a different loop` / `Event loop is closed`。`conftest.py` 的 autouse fixture 必须在每个测试后 `await engine.dispose()` 并关闭重建 Redis 客户端。生产每 worker 单 loop 不受影响（已实测复现）
- **httpx 的 `ASGITransport` 会缓冲整个响应体**，用它测 SSE 会把所有事件观测成同一时刻到达，无法验证流式。SSE 的 smoke test 必须起真实 uvicorn 走 TCP 断言首末事件时间差（已实测复现）

**开发第一天必须先跑通最小 smoke test**：FastAPI 异步路由 + asyncpg 查询 + Redis 读写 + 一个 SSE 端点 + 一个 WebSocket 端点，全部通过后再写业务。

### 12.3 外键依赖与数据操作顺序

拓扑排序（父 → 子）：

```
users → invite_codes
users → channels → model_channels ← models
users → conversations → messages
users → rooms → room_members
             → room_join_requests
             → messages
users/rooms/models/channels → usage_logs → daily_usage
users → audit_logs
users → notifications
users → settings
```

- **种子数据插入顺序**：users(admin) → settings → channels → models → model_channels → 示例房间
- **测试数据清理顺序（逆序）**：daily_usage → usage_logs → notifications → audit_logs → messages → room_join_requests → room_members → rooms → model_channels → models → channels → conversations → invite_codes → settings → users
- **级联策略与理由**：

| 关系 | 策略 | 理由 |
|------|------|------|
| users → conversations / room_members / room_join_requests | CASCADE | 用户删除后其私有数据无保留价值 |
| users → rooms | **RESTRICT** | 房间有他人消息，禁止因删用户而连带删房间；必须先转让或归档 |
| users → messages.sender_id | SET NULL | 保留消息内容，仅清除发言人（AI 消息本来就是 NULL） |
| users → usage_logs.user_id / owner_id | CASCADE | 用量明细随用户删除；**daily_usage 保留**（成本对账需要） |
| users → audit_logs.actor_id | SET NULL | 审计必须保留，只清操作人关联 |
| users → notifications | CASCADE | 通知属个人私有数据 |
| rooms → notifications | CASCADE | 房间删除后其通知无意义 |
| rooms → messages / room_members | CASCADE | 房间删除即删其消息 |
| channels → model_channels | CASCADE | 渠道删除自动解绑 |
| models → messages.model_id | SET NULL | 模型下线不影响历史消息 |
| usage_logs → messages.usage_log_id | SET NULL | 账本保留，消息可独立删除 |

### 12.4 全局副作用与测试隔离

| 副作用 | 内容 | 测试后处理 |
|--------|------|-----------|
| Redis | 配额计数、路由缓存、房间锁、限流窗口、在线状态、JWT 黑名单 | 每个测试后 `FLUSHDB`（测试用 **db=15**，开发 db=0，生产 db=0） |
| PostgreSQL | 全部业务表 | 事务回滚优先；跨事务测试按 FK 逆序 DELETE |
| 文件系统 | 上传临时目录、导出 CSV、日志 | `tmp_path` fixture + 测试后清理 |
| 环境变量 | `SETTINGS_*`、`CHANNEL_CIPHER_KEY` | `monkeypatch` 设置，自动恢复 |
| 进程内单例 | 设置缓存、加密器实例、连接池 | 提供 `reset_singletons()` 供 fixture 调用 |
| 上游模型调用 | 真实 API | **一律 mock**（`respx` 拦截 httpx），测试禁止真调；连通性测试单独标记 `@pytest.mark.live` 且默认跳过 |

`conftest.py` 必须包含的 autouse fixture（**在写第一个测试文件之前设计好**）：

```python
@pytest.fixture(autouse=True)
async def clean_state(db_session, redis_test, tmp_path, monkeypatch):
    yield
    # 1. Redis：FLUSHDB（db=15）
    # 2. DB：按 FK 逆序清理（或事务回滚）
    # 3. 文件：清理 tmp_path
    # 4. 单例：reset_singletons()
```

### 12.5 本地与生产环境差异

| 维度 | 本地开发 | 生产 | 常见踩坑 |
|------|---------|------|---------|
| 操作系统 | macOS / Windows | Linux（容器） | 路径分隔符、文件名大小写敏感 |
| Python | 3.12.x | 3.12-slim 镜像 | 镜像缺系统库（如 `libpq`），需 `build-essential` |
| PostgreSQL | 容器 16 | 容器 16 | 版本必须一致，否则 dump/restore 有差异 |
| 时区 | 本地（Asia/Shanghai） | **UTC** | `datetime.now()` 差 8 小时，配额日切错误 |
| 域名 | `http://localhost:5173` | `https://your-domain.com` | 混合内容被浏览器拦截；CORS 未加白名单 |
| 前后端 | Vite dev server 代理 | Caddy 同源反代 | 本地正常、线上 404（`/api` 前缀丢失） |
| HTTPS | 无 | 有 | `Secure` Cookie、WSS 协议头 |
| 数据量 | 几十条 | 几十万条 | 无索引全表扫描、分页 offset 过大 |
| 连接池 | 默认 5 | 10+10 | 连接耗尽、`pool_timeout` 报错 |
| 出网 | 无限制 | 海外机房 | 上游模型接口可达性不同；国内模型接口海外可直连 |
| SSE 缓冲 | 直连无代理 | 经 Caddy | **未关缓冲则流式失效**（最高频事故） |

### 12.6 数据库与 ORM 注意

- 连接池：`pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=1800, pool_timeout=10`。**注意 pool 是每 worker 独立的**，总量 = workers × (pool_size + max_overflow)，2 workers 即 20 条；改动 `--workers` 必须重算 9.6 的连接数精算表
- 禁止 lazy loading（见 12.2）
- **事务边界**：
  - 配额预扣（用户级 + 房间级两次 UPSERT）必须在**同一事务**内，任一失败整体回滚
  - 消息落库 + `usage_logs` 更新 + `daily_usage` 结算在同一事务
  - **上游模型调用绝不能在事务内**（长事务会占死连接）：先提交预扣事务 → 调模型 → 再开结算事务
  - 广播（Redis PUBLISH）在事务**提交后**执行，避免"广播了但回滚了"的幽灵消息
- Migration 多 head：用 `alembic merge` 合并，禁止 `stamp` 绕过

---

## 13. 测试策略

### 13.1 基础设施验证（第一天必做）

`tests/smoke/test_stack.py`：验证 FastAPI 异步路由 + asyncpg 连接 + Redis PING + SSE 分块输出 + WebSocket 收发 + Alembic 迁移可执行。全绿才允许写业务代码。

- 测试数据库：`ai_chatroom_test`（独立库，不复用开发库）
- 测试 Redis：`db=15`
- 上游模型：`respx` 全量 mock，禁止真调

### 13.2 测试数据管理

- `conftest.py` 提供 `clean_state` autouse fixture（见 12.4）
- 工厂函数：`make_user(role='member')`、`make_channel(status='enabled')`、`make_model(public_name='smart')`、`make_room(owner=..., budget=...)`，均支持字段覆盖
- 固定时钟：涉及配额日切、冷却、超时的测试用 `freezegun` 或注入 `now_fn`，禁止 `sleep` 真实等待

### 13.3 后端测试用例

| 模块 | 必测场景 |
|------|---------|
| 认证 | 注册成功 / 邮箱重复 409 / 邀请码无效 422 / 邀请码用尽 / 密码错误 401（不区分字段）/ 连续失败锁定 423 / 封禁用户 403 / token 过期 401 / 登出后旧 token 失效 |
| 权限 | 普通用户访问 `/api/admin/*` → 403 / 非成员访问房间消息 → 403 / 非房主改房间 → 403 / 房间管理员不能删房间 / 用户 A 访问用户 B 的会话 → 403（不是 404 泄露存在性时统一 404） |
| 渠道路由 | 单渠道命中 / 多渠道按优先级 / 同优先级按权重分布（1000 次采样验证比例）/ 冷却中渠道被跳过 / 无可用渠道抛 `NO_CHANNEL_AVAILABLE` / 401 直接禁用不重试 / 429 换渠道 / 连续 3 次失败转 auto_disabled / 健康巡检恢复 |
| **配额（重点）** | 预扣成功 / 预扣超限被拒且不产生调用 / **并发 20 个请求同时扣减总量不超限（超卖测试）** / 结算多退少补精确 / 超时全额退回 / pending 超 10 分钟被兜底退回 / 房间预算与用户配额双闸门各自触发 / 熔断状态迁移 normal→warning→suspended→normal / 日切后额度恢复 |
| 房间 | 加入成功 / 满员被拒（并发加入不超员）/ 邀请码校验 / 审批流 / 禁言后不能发言 / **房间串行：并发 5 个 @AI 只有 1 个执行，其余返回排队位次** / 锁 TTL 到期后可再次获取 / 广播到达所有订阅者 / 断线重连增量补齐不重复 |
| 消息 | 发送落库 / 幂等键重复提交返回首次结果 / 敏感词输入侧拦截（不落库不扣费）/ 输出侧拦截（替换文案 + 按已产生 token 结算）/ 游标分页不重不漏 |
| SSE | 事件顺序 meta→delta*→usage→done / 首字超时返回 error 事件且 refund=true / 客户端断开后服务端仍完成落库 |
| 统计 | 三维度聚合数值与明细一致 / 时区正确（跨 UTC 午夜的记录归属正确的 quota_date）/ 告警阈值触发 |

### 13.4 前端验收标准

| 页面 | 验收点 |
|------|-------|
| 登录/注册 | tab 切换正确；注册态显示邀请码；错误提示逐字段；5 次失败显示锁定倒计时 |
| 消息列表 | 置顶置灰底 + 右上角折角；未读徽标；免打扰徽标不计入 tab 角标；草稿红字；下拉刷新；空态引导 |
| 房间列表 | 分类筛选生效；三种按钮态（进入/申请/已满）；卡片内长文本省略号不撑破 |
| 单聊 | SSE 打字机逐字渲染；首字延迟 < 1.5s 有占位动画；超时显示"重试"；切换模型后新消息用新模型且历史不串 |
| 房间 | 他人消息带昵称与头像色；AI 消息左侧蓝条 + "由 X 触发"标签；@AI 排队显示位次；熔断时 @AI 置灰并有系统消息；断线顶部提示并自动重连 |
| 我的 | 三条配额进度条数值与后端一致；主题切换全站生效并持久化；管理入口仅 admin 可见 |
| 管理后台（移动） | 渠道卡片展开/收起；新建渠道先选协议类型 → 表单按协议动态渲染 → 厂商预设一键填充；Key 只显示 hint；连通性测试显示延迟；停用最后一个渠道时二次确认文案含影响范围；统计四维切换；375 宽下无横向滚动且表格类数据已降级为卡片 |
| 管理后台（桌面） | ≥1024 双栏生效；列表切表格且可排序；权限矩阵表头吸顶、首列固定；编辑抽屉不遮挡主内容；统计图表并排不错位 |
| 全局 | 375 / 768 / 1440 三个宽度无横向滚动条；夜间主题下所有文字对比度 ≥ 4.5:1；所有图标正常渲染（无方框） |

### 13.5 压力测试

- 工具：`locust`
- 场景 A（常规）：30 虚拟用户，混合 70% 房间发言 + 20% 浏览 + 10% @AI，持续 10 分钟
- 场景 B（突发）：50 用户在 30 秒内同时进入同一房间并各发 1 条消息
- 场景 C（AI 并发）：20 个不同房间同时 @AI
- **通过标准**：场景 A 消息发送 P95 < 300ms、错误率 < 0.1%；场景 B 无消息丢失、无超员、P95 < 1s；场景 C 首字 P95 < 2s、配额扣减总量与 `daily_usage` 完全一致（**零误差**）、无 pending 悬挂

---

## 14. CI/CD 与部署方案

### 14.1 仓库结构（Monorepo）

```
ai-chatroom/
├── backend/            # FastAPI
├── frontend/           # Vue 3
├── deploy/             # Caddyfile、docker-compose、备份脚本
├── docs/               # 本 PRD、架构图、运维手册
├── scripts/            # 初始化、种子数据、迁移辅助
├── .github/workflows/  # CI
├── CLAUDE.md
└── README.md
```

### 14.2 Docker Compose（完整）

```yaml
# deploy/docker-compose.yml
name: ai-chatroom

services:
  postgres:
    image: postgres:16.4-alpine
    container_name: aicr-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"
      TZ: UTC
    command: >
      postgres -c max_connections=100
               -c log_min_duration_statement=500
               -c shared_buffers=128MB
               -c effective_cache_size=256MB
               -c idle_in_transaction_session_timeout=60000
               -c statement_timeout=60000
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 12
    networks: [internal]
    # 不映射端口到宿主机，仅内网可达
    deploy:
      resources:
        limits: { memory: 512M }

  redis:
    image: redis:7.2-alpine
    container_name: aicr-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "128mb",
              "--maxmemory-policy", "noeviction", "--requirepass", "${REDIS_PASSWORD}"]
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 5s
      timeout: 3s
      retries: 12
    networks: [internal]
    deploy:
      resources:
        limits: { memory: 160M }

  app:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.backend
    container_name: aicr-app
    restart: unless-stopped
    env_file: ../.env
    environment:
      TZ: UTC
      ROLE: web
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers"
    expose: ["8000"]
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/api/health',timeout=3).status_code==200 else 1)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 40s
    networks: [internal]
    deploy:
      resources:
        limits: { memory: 640M }

  scheduler:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.backend
    container_name: aicr-scheduler
    restart: unless-stopped
    env_file: ../.env
    environment:
      TZ: UTC
      ROLE: scheduler
    depends_on:
      app: { condition: service_healthy }
    command: ["python", "-m", "app.scheduler"]
    networks: [internal]
    deploy:
      resources:
        limits: { memory: 192M }
        replicas: 1          # 必须为 1，多副本会重复执行定时任务

  caddy:
    image: caddy:2.8-alpine
    container_name: aicr-caddy
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddydata:/data
      - caddyconfig:/config
      - ../frontend/dist:/srv:ro
    depends_on:
      app: { condition: service_healthy }
    networks: [internal]

volumes:
  pgdata:
  redisdata:
  caddydata:
  caddyconfig:

networks:
  internal:
    driver: bridge
```

**内存精算（4GB 物理内存）**

| 进程 | 容器限额 | 稳态预期 |
|------|---------|---------|
| PostgreSQL | 512M | 约 300M（shared_buffers 128M + 连接开销） |
| Redis | 160M | 约 40M（maxmemory 128mb 硬上限） |
| app（2 workers） | 640M | 约 380M |
| scheduler | 192M | 约 90M |
| Caddy | 未限 | 约 40M |
| 宿主机 + Docker daemon | — | 约 400M |
| **合计** | — | **约 1.25G / 4G ≈ 31%** ✓ |

余量充足，但仍须开 2G swap 兜底 AI 流式高峰；`app` 内存 > 550M 持续 5 分钟触发 P2 告警（排查见 23.2）。

### 14.3 Caddyfile（关键：SSE 与 WebSocket）

> **域名已具备**（项目负责人确认）。落地时把下方 `your-domain.com` 全量替换为实际域名，并同步更新 `.env` 的 `APP_BASE_URL`、`DOMAIN`、`CORS_ORIGINS` 与 CSP 的 `connect-src`。建议：主域给前端，`api.` 子域留作将来 API 独立部署（V1 同源即可，无需拆分）。上线前 DNS TTL 降到 300s。

```
{
  email {ACME_EMAIL}
  servers {
    protocols h1 h2 h2c
  }
}

your-domain.com {
  encode zstd gzip

  header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains"
    X-Content-Type-Options "nosniff"
    X-Frame-Options "DENY"
    Referrer-Policy "strict-origin-when-cross-origin"
    Content-Security-Policy "default-src 'self'; connect-src 'self' wss:; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com"
    -Server
  }

  # SSE：必须关缓冲、关超时截断
  @sse path /api/*/ai/completions /api/*/ai/ask
  handle @sse {
    reverse_proxy app:8000 {
      flush_interval -1
      transport http {
        read_timeout 300s
        dial_timeout 5s
      }
    }
  }

  # WebSocket
  @ws path /ws/*
  handle @ws {
    reverse_proxy app:8000 {
      transport http {
        read_timeout 3600s
        write_timeout 3600s
      }
    }
  }

  # 后端 API
  handle /api/* {
    reverse_proxy app:8000 {
      transport http { read_timeout 30s }
    }
  }

  # 前端 SPA
  handle {
    root * /srv
    try_files {path} /index.html
    file_server
  }

  log {
    output file /data/access.log { roll_size 50MiB roll_keep 10 }
    format json
  }
}
```

### 14.4 部署流程

**首次部署**

```bash
ssh user@server
sudo apt update && sudo apt install -y docker.io docker-compose-plugin ufw fail2ban
sudo ufw allow 22,80,443/tcp && sudo ufw enable
git clone <repo> && cd ai-chatroom
cp .env.example .env && vim .env          # 填全部密钥
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml exec app python -m scripts.seed  # 创建 admin + 默认设置
cd frontend && npm ci && npm run build    # 或在 CI 中构建后 rsync dist
```

**日常更新**

```bash
git pull
docker compose -f deploy/docker-compose.yml build app scheduler
docker compose -f deploy/docker-compose.yml up -d app scheduler   # 自动执行 alembic upgrade head
cd frontend && npm ci && npm run build && rsync -a dist/ ../frontend/dist/
curl -s https://your-domain.com/api/health | jq .                 # Smoke
```

**CI（GitHub Actions）**：push 到 `main` → lint（ruff + eslint）→ 类型检查（mypy）→ 测试（起 postgres/redis service container）→ `pip-audit` + `npm audit` → 构建镜像推 registry → 手动 approval 后 SSH 部署。

### 14.5 本地开发环境

```bash
# 后端
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env               # 填本地值
docker compose -f deploy/docker-compose.dev.yml up -d postgres redis
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm install && npm run dev   # http://localhost:5173，代理 /api → :8000

# 测试
pytest -q                                  # 用独立测试库 + Redis db=15
pytest -m live --run-live                  # 真实调上游（需手动开启，默认跳过）
```

### 14.6 多环境差异

| 变量 | Dev | Staging | Prod |
|------|-----|---------|------|
| `ENVIRONMENT` | development | staging | production |
| `DEBUG` | true | false | false |
| `DOCS_ENABLED` | true | true | **false** |
| `DATABASE_URL` | 本地容器 | 独立库 | 独立库 |
| `REDIS_DB` | 0 | 1 | 0 |
| `CORS_ORIGINS` | localhost:5173 | staging 域名 | 正式域名 |
| `JWT_SECRET` | 开发用固定值 | 独立随机 | 独立随机（≥32 字节） |
| `CHANNEL_CIPHER_KEY` | 开发用 | 独立 | 独立（**泄露需数据迁移**） |
| `LOG_LEVEL` | DEBUG | INFO | INFO |
| `UVICORN_WORKERS` | 1 | 2 | 2 |
| 上游模型 | mock / 便宜模型 | 真实小额 | 真实 |

---

## 15. 架构韧性设计

### 15.1 单点故障识别

| 组件 | 是否单点 | V1 接受 | V2 消除方案 |
|------|---------|--------|-----------|
| Caddy | 是 | ✓ | 前置云厂商 LB + 双实例 |
| FastAPI app | 是（2 worker 同进程组） | ✓ | 多实例 + LB（代码已无状态，零改造） |
| scheduler | 是（**必须单实例**） | ✓ | 多副本 + Redis 选主锁 |
| PostgreSQL | 是 | ✓ | 流复制主从 + 自动故障转移（Patroni） |
| Redis | 是 | ✓ | 哨兵或云托管 Redis |
| 上游模型 API | 外部依赖 | ✓ | 多渠道 fallback（已实现，见 5.3） |
| 服务器整机 | 是 | ✓ | 双机热备 / 云厂商高可用组 |

### 15.2 故障影响矩阵

| 故障组件 | 完全不可用 | 降级可用 | 不受影响 |
|---------|-----------|---------|---------|
| PostgreSQL | 全部功能 | — | — |
| Redis | AI 调用（配额无法原子判定）、房间广播、限流 | 单聊可降级为**直查 `daily_usage` 表判定配额**（性能下降但可用）；房间消息降级为 HTTP 轮询（`GET /api/rooms/{id}/messages?after=`，前端 3s 轮询） | 登录、浏览历史消息、管理端只读页面 |
| 上游模型 API | AI 回复 | 自动切备用渠道；全部失败则提示不可用 | **成员之间的聊天完全不受影响**（这是产品设计的核心韧性） |
| Caddy | 全站 | — | — |
| scheduler | 无即时影响 | 健康巡检、pending 兜底、备份停摆 | 全部在线功能 |
| 对象存储（备份目标） | 无即时影响 | 备份失败告警 | 全部在线功能 |

**Redis 降级细节**：配额判定回落到 `daily_usage` 表的条件 UPSERT（本就是真相源，只是少了缓存加速）；房间串行锁回落到 `SELECT ... FOR UPDATE` 行锁；广播回落到轮询。这套降级路径必须在测试中覆盖，不能只写在文档里。

### 15.3 RTO / RPO

| 指标 | 目标 | 依据 |
|------|------|------|
| RTO | 1 小时 | 面向小范围用户的工具型产品，非交易/公共服务 |
| RPO | 1 小时 | 每日全量备份 + PostgreSQL WAL 归档到对象存储（`archive_timeout=3600`） |

达成手段：Docker `restart: unless-stopped` 自动拉起；备份每小时归档 WAL、每日 03:00 全量；恢复演练每季度一次（**备份没验证过恢复等于没有备份**）。

### 15.4 熔断器（对上游模型）

```
CLOSED（正常）
  → 连续 3 次失败 或 60s 内失败率 > 50%（至少 5 次请求）
OPEN（熔断，cooldown_until = now + 60s）
  → 60s 后
HALF-OPEN（放 1 个试探请求）
  → 成功：CLOSED，fail_count 归零
  → 失败：OPEN，cooldown 翻倍（60s → 120s → 240s，上限 900s）
```

- 实现：`channels.fail_count` + `channels.cooldown_until` 字段 + Redis 计数器（`cb:{channel}:fails`，TTL 60s）
- 前端表现：熔断期间该渠道不参与选路，用户无感（走备用渠道）；无备用渠道时提示"该模型暂不可用"
- 状态变更写 WARN 日志 + 审计 + 管理员通知

### 15.5 自动恢复

| 故障 | 恢复机制 |
|------|---------|
| 进程崩溃 | Docker `restart: unless-stopped` + healthcheck |
| DB 连接断开 | `pool_pre_ping=True` 自动剔除；`pool_recycle=1800` |
| Redis 断连 | 客户端自动重连 + 降级路径（15.2） |
| 上游超时 | 熔断器 + 指数退避 + 换渠道 |
| 磁盘 ≥ 80% | 告警 + 自动清理 7 天前日志与临时导出文件 |
| 磁盘 ≥ 90% | CRITICAL 告警 + 停止写审计以外的非关键日志 |
| pending 用量悬挂 | scheduler 每 10 分钟兜底退回 |

### 15.6 优雅降级层级

| 级别 | 触发 | 用户可用 | 用户看到 | 运维动作 |
|------|------|---------|---------|---------|
| L0 正常 | — | 全部 | 无 | 无 |
| L1 部分降级 | 部分渠道熔断 | 全部（走备用渠道） | 无感 | 查看渠道健康，联系上游 |
| L2 AI 降级 | 所有渠道不可用 | 房间聊天、历史查看、管理端 | "AI 服务暂时不可用，成员之间仍可正常交流" | 检查出网、Key 余额、上游状态页 |
| L3 只读 | PostgreSQL 只读（磁盘满/主从切换） | 浏览历史 | "系统维护中，暂时无法发送消息" | 紧急扩容或切换主库 |
| L4 静态维护页 | app 完全不可用 | 无 | Caddy 返回静态维护页 | 按事故响应流程处理 |
| L5 完全不可达 | 服务器/域名不可达 | 无 | 浏览器错误 | 通过群/邮件通知用户 |

L4 的静态维护页由 Caddy 在 `app` 健康检查失败时自动 fallback 到 `/srv/maintenance.html`。

### 15.7 超时分级

| 操作 | 超时 | 用户体验 | 超时后 |
|------|------|---------|--------|
| 普通 API | 3s | 骨架屏 | "网络异常，请重试" |
| 登录 | 10s | 按钮 loading | "登录超时，请重试" |
| AI 首字 | 15s | 三点跳动动画 | error 事件 + 退回额度 + "重试"按钮 |
| AI 整体 | 60s | 流式已显示部分内容 | 保留已收内容 + "回复未完成，可追问继续" |
| 连通性测试 | 15s | 按钮 loading | "测试失败：连接超时" |
| 文件上传（V2） | 60s | 进度条 | "上传失败，请检查网络" |
| CSV 导出 | 5min | 转后台 + 站内通知 | 通知失败原因 |

### 15.8 Fallback 清单

| 依赖 | 正常来源 | Fallback | 用户感知 |
|------|---------|---------|---------|
| AI 回复 | 首选渠道 | 备用渠道 → 全部失败提示 | 无感 / 明确提示 |
| 房间广播 | WebSocket | HTTP 轮询（3s） | 顶部"连接中…"，消息延迟 ≤3s |
| 配额判定 | Redis 计数 | `daily_usage` 表直查 | 无感（略慢） |
| token 用量 | 上游 usage 字段 | tiktoken 本地估算 | 无感（日志标记 estimated） |
| 系统设置 | Redis 缓存 | 进程内默认值 → DB | 无感 |
| 用户头像 | 上传（V2） | 昵称首字 + 稳定配色 | 无感 |
| 模型单价 | `models` 表 | 单价为 0，成本记 0 并告警 | 统计页显示"单价未配置" |

---

## 16. 状态一致性（配额账本）

本项目不涉及支付，但**配额预扣—结算—退回是一套典型的跨系统状态机**，必须按此标准设计。

### 16.1 usage_logs 状态机

```
                    ┌──────────────┐
   预扣成功 ───────► │   pending    │
                    └──────┬───────┘
        ┌──────────────────┼──────────────────┬───────────────┐
        ▼                  ▼                  ▼               ▼
  ┌──────────┐      ┌────────────┐     ┌────────────┐  ┌────────────┐
  │ settled  │      │  refunded  │     │   failed   │  │ (悬挂>10m) │
  │ 正常结算  │      │ 全额退回    │     │ 调用前失败  │  │ 兜底→refunded│
  └──────────┘      └────────────┘     └────────────┘  └────────────┘
   上游成功返回       超时/中断/取消/       预扣后立即失败     scheduler 扫描
   按实扣减          输出侧内容拦截        （未扣减）
```

**禁止的迁移**：`settled → refunded`（已结算不可再退，如有争议走人工调整并写审计）；`pending` 是唯一中间态，**任何 pending 记录最终必须落到终态**，由 scheduler 兜底保证。

### 16.2 三层保障

| 层 | 机制 |
|----|------|
| 第一层 实时结算 | 流结束（`done` 事件）立即结算；异常路径立即退回 |
| 第二层 连接级兜底 | 客户端断开时，服务端不中断上游，收完流后照常结算落库（`try/finally` 保证） |
| 第三层 定时对账 | scheduler 每 10 分钟扫 `pending AND created_at < now()-10min` → 强制 refund + 告警；每日 00:05 用 `usage_logs` 重算 `daily_usage` 与 Redis 计数，三者不一致时以 `usage_logs` 聚合值为准并告警 |

### 16.3 不一致处理

对账发现差异时：写 `audit_logs(action='quota.reconcile_mismatch')`，自动生成管理员告警卡，提供"一键以账本为准重算"操作（需二次确认）。所有人工调整必须记录调整前后值与操作人。

---

## 17. 第三方服务风险管理

### 17.1 服务清单

| 服务 | 用途 | 配额/限制 | 费用模型 | 扩容方式 | 冷启动风险 |
|------|------|----------|---------|---------|-----------|
| 阿里百炼（DashScope） | 主力模型 | 新账号有免费额度与 QPS 限制，按模型不同 | 按 token | 控制台申请提额 | **中**：新账号需实名 + 开通服务，国际站需单独开通 |
| DeepSeek | 主力模型 | 有 RPM/TPM 限制，充值后生效 | 按 token | 充值即扩 | **低**：注册充值即可用 |
| OpenAI | 备用模型 | 新账号 TPM 低，需累计消费提额（Tier 制度） | 按 token | 累计消费自动升 Tier | **高**：新账号限额严格，需养号 1-2 周；需海外支付方式 |
| OpenRouter | 聚合备用 | 按上游透传，自身限额宽松 | 按 token + 少量加价 | 充值即扩 | **低**：一个 Key 覆盖多家，适合作为万能兜底 |
| VPS 云厂商（**待选定**） | 服务器 | 单机资源 | 月付 | 升配需重启 | 低 |
| 域名注册商 | 域名 | — | 年付 | — | 低 |
| Cloudflare（可选） | CDN/DNS | 免费版有 HTTP 响应约 100s 超时 | 免费 | — | **注意**：长流式回复可能被截断，上线前必须实测 |
| R2 / B2 对象存储 | 备份 | 免费额度充足 | 存储 + 出口（R2 出口免费） | — | 低 |
| UptimeRobot / Better Stack | 可用性监控 | 免费版 50 个监控点 | 免费 | — | 低 |

### 17.2 冷启动预热计划

| 时间 | 任务 |
|------|------|
| D-14 | 注册所有模型平台账号，完成实名/开通；OpenAI 首充小额开始养号 |
| D-10 | 各平台创建 API Key，在测试环境跑通连通性；记录各账号初始 TPM/RPM |
| D-7 | 申请必要的提额（百炼/DeepSeek 通常即时或 1 个工作日） |
| D-5 | 购买域名 + VPS，配置 DNS（TTL 300s），Caddy 签发证书 |
| D-3 | 全链路压测，记录各渠道实际首字延迟与限流阈值 |
| D-1 | 灰度：发 10 个邀请码给内部用户 |
| D0 | 正式上线 |

### 17.3 费用预警

- 房间级：`daily_token_budget`，80% 预警、100% 熔断（已设计，见 5.6.5）
- 用户级：`daily_token_limit`，同上
- **全局级（新增）**：`settings.global_monthly_budget`，每日 00:10 由 scheduler 汇总当月 `daily_usage.cost`，达 80% 推送管理员，达 100% 触发全局降级开关 `feature_flags.room_ai=false`（保留单聊，关闭房间 AI），并强制通知
- 上游余额：每日巡检各渠道余额（若上游提供接口），低于阈值告警

### 17.4 备选方案

| 关键依赖 | 备选 | 切换成本 |
|---------|------|---------|
| 主力模型（百炼/DeepSeek） | OpenRouter 聚合 → 覆盖 OpenAI/Anthropic/Gemini/Groq 等 | **零代码**，管理端加渠道 + 绑定模型即可 |
| VPS | 任意支持 Docker 的海外 VPS | 低：`docker compose` 一键迁移 + 恢复备份 |
| 对象存储 | R2 ↔ B2 ↔ S3 | 低：改 endpoint 与凭证 |
| 反向代理 | Caddy ↔ Nginx | 中：需重写反代配置（SSE 缓冲处理不同） |
| PostgreSQL | 自建 ↔ Neon/Supabase 托管 | 低：改 `DATABASE_URL` |

---

## 18. 事故响应流程

### 18.1 分级与响应

| 级别 | 定义 | 响应 | 恢复目标 |
|------|------|------|---------|
| P0 | 全站不可用 / 数据丢失 / 密钥泄露 | 15 分钟内 | 1 小时 |
| P1 | 核心功能不可用（无法登录、AI 全部不可用、消息发不出） | 30 分钟内 | 4 小时 |
| P2 | 非核心异常（统计错、导出失败、通知不发） | 2 小时内 | 24 小时 |
| P3 | 体验问题（UI 错位、文案错） | 下个工作日 | 下个版本 |

### 18.2 升级路径

值班（项目负责人本人）→ 30 分钟未解决则启动人工应急（18.4）→ 涉及密钥泄露或数据丢失立即执行 18.5 用户沟通 + 密钥轮换。

单人项目现实约束：**没有 7×24 值班**。因此 P0 的兜底是自动化：Docker 自动重启 + 熔断降级 + 监控告警推送到手机 + 静态维护页，确保"最坏情况下用户看到的是明确的维护提示，而不是白屏或数据错乱"。

### 18.3 应急联系人

| 角色 | 责任 | 联系方式 |
|------|------|---------|
| 项目负责人 | 全部 | （填写） |
| VPS 厂商支持 | 硬件/网络 | 工单系统 |
| 模型厂商支持 | 上游故障/限额 | 各平台工单 |
| 域名/CDN | DNS 切换 | 控制台 |

### 18.4 人工应急预案

| 场景 | 兜底方案 |
|------|---------|
| AI 全渠道不可用 | 公告说明；房间聊天照常；必要时临时提高某渠道优先级或换 OpenRouter |
| 数据库损坏 | 从最近全量备份 + WAL 归档恢复到指定时间点；恢复期间挂静态维护页 |
| 密钥泄露 | 立即在各平台吊销 Key → 管理端替换 → 轮换 `CHANNEL_CIPHER_KEY`（需迁移脚本）→ 查审计日志定位泄露范围 → 通知受影响用户 |
| 配额被恶意刷穿 | 立即把 `settings.registration.mode` 改 `closed`；封禁相关用户；调低全局预算；排查是否泄露邀请码 |
| 服务器欠费/被封 | 用备份在新 VPS 恢复（目标 1 小时内）；DNS 切换（TTL 300s） |
| 完全无法恢复 | 群/邮件通知用户，导出所有消息数据分发 |

### 18.5 用户沟通模板

```
【维护公告】
LinkAI当前遇到技术问题，正在紧急修复。
影响范围：{AI 回复暂时不可用 / 全站无法访问}
成员之间的聊天{不受影响 / 暂时不可用}。
预计恢复时间：{时间}
期间如有问题请联系：{联系方式}

【恢复公告】
LinkAI已于 {时间} 恢复正常。
如你在故障期间遇到额度异常或消息丢失，请联系 {联系方式}，我们会逐一核对处理。
```

### 18.6 复盘模板

P0/P1 事故 48 小时内产出：基本信息（时间/影响范围/影响用户数/级别）→ 时间线（时间/事件/操作人）→ 5 Whys 根因 → 改进措施（措施/责任人/完成时间）→ 教训（聚焦流程，不追责个人）。归档到 `docs/postmortems/`。

---

## 19. 开发里程碑

| 周 | 交付物 | 验收标准 |
|----|--------|---------|
| **W0（并行）** | 域名 + VPS 采购、模型平台账号注册与养号、`.env` 密钥准备 | 各渠道 Key 在本地能跑通一次调用 |
| **W1** | 脚手架 + smoke test + 数据模型 + 迁移 + 认证 + 邀请码 + 管理端渠道 CRUD + 密钥加密 + 连通性测试 | `tests/smoke` 全绿；能注册登录；能在管理端加渠道并测试通过；**配额并发超卖测试通过** |
| **W2** | 单聊闭环：会话 CRUD + 渠道路由 + SSE 流式 + 参数白名单 + 配额预扣/结算/退回 + 敏感词 | 打字机效果可见；首字 P95 < 1.5s；超时能退回额度；切换模型不串上下文 |
| **W3** | 房间：房间 CRUD + 准入 + 成员管理 + WebSocket 广播 + @AI + 房间串行队列 + 房主配额归属 + 熔断状态机 | 多人同时聊天消息不丢不重；并发 5 个 @AI 只有 1 个执行；预算耗尽自动熔断并广播 |
| **W4** | 管理后台（移动端完整形态）：渠道管理（协议选择 + 厂商预设）+ 模型注册表 + 用户管理 + 邀请码 + 系统设置 | 在 375 宽下能走完"新建渠道 → 选协议 → 填 Key → 测试连通 → 绑定模型 → 启用"全流程；Key 只回显 hint |
| **W5** | 统计与治理 + 后台桌面形态：四维统计 + 告警 + 审计日志 + 房间管理；≥1024 双栏与表格布局 | 统计数值与明细账本零误差；告警可触发；1440 宽下表格排序与抽屉编辑可用；375/768/1440 三断点均无横向滚动 |
| **W6** | 部署上线：Caddy + HTTPS + Docker Compose + 备份 + 监控 + 压测 + 灰度 10 人 | 压测三场景通过；备份恢复演练成功；灰度 3 天无 P0/P1 |

> **周期说明**：v1.0 规划 5 周；v1.1 因管理后台从"桌面为主、移动只读"改为"**桌面与移动端均完整**"，前端工作量增加约 40%，总周期顺延为 **6 周**。若需压回 5 周：把 W5 的桌面表格布局延后到 V1.1 补丁（先只交付移动端完整后台，桌面端沿用移动布局居中显示），功能不减、仅视觉延后。

**推荐开发模式**：单 Agent（Claude Code）+ 人工验收。项目规模不需要 Agent Teams；但每周末必须人工走查一遍核心流程（阶段四的用户走查），不要只看测试通过。

---

## 20. 环境变量与配置

### 20.1 `.env.example`（提交到 Git，值留空或占位）

```bash
# ── 基础 ─────────────────────────────────────────────
ENVIRONMENT=production            # development | staging | production
DEBUG=false
LOG_LEVEL=INFO                    # DEBUG | INFO | WARN | ERROR
APP_BASE_URL=https://your-domain.com
ACME_EMAIL=admin@your-domain.com  # Caddy 证书申请邮箱
DOMAIN=your-domain.com

# ── 数据库（敏感，不入代码库）──────────────────────────
POSTGRES_DB=ai_chatroom
POSTGRES_USER=ai_chatroom
POSTGRES_PASSWORD=__CHANGE_ME_32_CHARS__
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10

# ── Redis（敏感）─────────────────────────────────────
REDIS_PASSWORD=__CHANGE_ME_32_CHARS__
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
REDIS_DB=0                        # 测试环境用 15

# ── 认证密钥（敏感，≥32 字节随机，泄露需轮换）────────────
JWT_SECRET=__CHANGE_ME_openssl_rand_hex_32__
JWT_SECRET_PREV=                  # 轮换过渡期使用，平时留空
JWT_EXPIRE_DAYS=7

# ── 渠道 Key 加密（敏感，泄露需数据迁移）────────────────
CHANNEL_CIPHER_KEY=__CHANGE_ME_fernet_key__

# ── 业务默认值（可在管理端「系统设置」覆盖）───────────────
DEFAULT_DAILY_MSG_LIMIT=50
DEFAULT_DAILY_TOKEN_LIMIT=100000
DEFAULT_ROOM_DAILY_TOKEN_BUDGET=500000
QUOTA_WARN_RATIO=0.8
QUOTA_RESET_TZ=Asia/Shanghai      # 配额日切时区，禁止改成 UTC
REGISTRATION_MODE=invite_code     # open | invite_code | closed
MODERATION_ENABLED=true
AI_FIRST_TOKEN_TIMEOUT_MS=15000
AI_TOTAL_TIMEOUT_MS=60000
ROOM_AI_COOLDOWN_SEC=5
ROOM_CONTEXT_WINDOW=20
ROOM_CONTEXT_TOKEN_LIMIT=8192
GLOBAL_MONTHLY_BUDGET=200         # 单位：元，达 80% 告警，100% 关房间 AI

# ── 上游模型（运行时全部走渠道表，env 仅用于初始化种子渠道）──
# 按【协议类型】分组，同协议可配多个（_1 _2 后缀）；留空则跳过该渠道
SEED_OPENAI_COMPAT_1_NAME=
SEED_OPENAI_COMPAT_1_BASE_URL=
SEED_OPENAI_COMPAT_1_KEY=
SEED_OPENAI_COMPAT_2_NAME=
SEED_OPENAI_COMPAT_2_BASE_URL=
SEED_OPENAI_COMPAT_2_KEY=
SEED_ANTHROPIC_KEY=
SEED_GEMINI_KEY=

# ── 备份与监控（敏感）─────────────────────────────────
BACKUP_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com
BACKUP_S3_BUCKET=ai-chatroom-backup
BACKUP_S3_ACCESS_KEY=
BACKUP_S3_SECRET_KEY=
BACKUP_GPG_RECIPIENT=
UPTIMEROBOT_NOTIFY_EMAIL=
ADMIN_NOTIFY_EMAIL=

# ── 特性开关（灰度与紧急降级用）────────────────────────
FEATURE_ROOM_AI=true
FEATURE_WEB_SEARCH=false
FEATURE_VOICE_INPUT=false
FEATURE_FILE_UPLOAD=false
DOCS_ENABLED=false                # 生产必须 false
CORS_ORIGINS=https://your-domain.com
```

### 20.2 运行时可调配置（改后无需重启）

存 `settings` 表，管理端「系统设置」页可改，Redis 缓存 300s + 主动失效：

全局每日消息上限、全局每日 token 上限、房间默认日预算、预警比例、注册方式、内容安全开关与词库版本、AI 冷却秒数、房间上下文窗口与 token 上限、全局月预算、消息保留天数。

### 20.3 特性开关（Feature Flag）

| 开关 | 默认 | 用途 |
|------|------|------|
| `feature_flags.room_ai` | true | **紧急降级用**：全局月预算耗尽或上游大面积故障时一键关闭房间 AI，保留成员聊天 |
| `feature_flags.web_search` | false | 联网检索（V2） |
| `feature_flags.voice_input` | false | 语音输入（V2） |
| `feature_flags.file_upload` | false | 文件上传（V2，开启前必须实现文件头校验与存储隔离） |
| `registration.mode` | invite_code | 被刷时紧急切 `closed` |

`.gitignore` 必须包含：`.env`、`*.pem`、`*.key`、`backups/`、`frontend/dist/`、`__pycache__/`、`.venv/`、`node_modules/`。

---

## 21. 项目目录结构

```
ai-chatroom/
├── CLAUDE.md                          # AI 编程工具入口，指向本 PRD
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── LinkAI-PRD-v1.md              # 本文档
│   ├── architecture.md                # 架构图与决策记录（ADR）
│   ├── runbook.md                     # 运维手册（见 23 章）
│   └── postmortems/                   # 事故复盘归档
├── deploy/
│   ├── docker-compose.yml             # 生产编排（见 14.2）
│   ├── docker-compose.dev.yml         # 本地只起 postgres + redis
│   ├── Dockerfile.backend             # python:3.12-slim，非 root 用户
│   ├── Dockerfile.frontend            # node:20-alpine 构建 → 产出 dist
│   ├── Caddyfile                      # 反代 + SSE/WS 配置（见 14.3）
│   └── scripts/
│       ├── backup.sh                  # pg_dump → gzip → gpg → rclone 上传
│       ├── restore.sh                 # 恢复演练用
│       └── logrotate.sh
├── backend/
│   ├── alembic/
│   │   ├── env.py                     # 异步迁移配置
│   │   ├── script.py.mako
│   │   └── versions/                  # 迁移脚本
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py                    # FastAPI 实例、中间件、异常处理器、路由挂载
│   │   ├── scheduler.py               # APScheduler 入口（独立容器运行）
│   │   ├── config.py                  # Pydantic Settings 读 env
│   │   ├── deps.py                    # get_db / get_redis / get_current_user / require_admin
│   │   ├── core/
│   │   │   ├── security.py            # argon2 哈希、JWT 签发校验、黑名单
│   │   │   ├── crypto.py              # Fernet 加解密渠道 Key
│   │   │   ├── errors.py              # 业务异常类 + 错误码常量
│   │   │   ├── logging.py             # structlog 配置、trace_id 中间件
│   │   │   ├── ratelimit.py           # Redis 滑动窗口限流
│   │   │   ├── idempotency.py         # Idempotency-Key 处理
│   │   │   └── timeutil.py            # quota_date 计算（Asia/Shanghai）
│   │   ├── models/                    # SQLAlchemy ORM 模型（每表一文件）
│   │   │   ├── user.py  invite_code.py  channel.py  model.py
│   │   │   ├── conversation.py  room.py  room_member.py  message.py
│   │   │   └── usage_log.py  daily_usage.py  audit_log.py  setting.py
│   │   ├── schemas/                   # Pydantic v2 请求/响应模型
│   │   │   ├── auth.py  channel.py  model.py  conversation.py
│   │   │   ├── room.py  message.py  quota.py  stats.py  admin.py
│   │   │   └── sse.py                 # SSE 事件体定义
│   │   ├── api/
│   │   │   ├── router.py              # 总路由聚合
│   │   │   ├── auth.py  conversations.py  rooms.py  models.py  quota.py
│   │   │   ├── ws.py                  # WebSocket /ws/rooms/{id}
│   │   │   └── admin/
│   │   │       ├── channels.py  models.py  users.py  rooms.py
│   │   │       ├── invites.py  stats.py  settings.py  audit.py
│   │   ├── services/
│   │   │   ├── auth_service.py
│   │   │   ├── channel_service.py     # 渠道 CRUD、加密、连通性测试、同步模型
│   │   │   ├── router_service.py      # 选路、加权随机、熔断、fallback
│   │   │   ├── adapter/
│   │   │   │   ├── base.py            # ProtocolAdapter 抽象 + UnifiedRequest / StreamEvent
│   │   │   │   ├── openai_compat.py   # OpenAI 协议（覆盖面最广）
│   │   │   │   ├── anthropic.py       # Anthropic Messages 协议
│   │   │   │   ├── gemini.py          # Gemini generateContent 协议
│   │   │   │   ├── presets.py         # 厂商预设：协议 → base_url / 默认超时 / 参数白名单
│   │   │   │   └── registry.py        # protocol → adapter 分发表
│   │   │   ├── quota_service.py       # freeze / settle / refund / reconcile
│   │   │   ├── streamer.py            # SSE 事件封装、首字计时、中断处理
│   │   │   ├── broadcast.py           # Redis pub/sub 房间广播
│   │   │   ├── room_service.py        # 房间 CRUD、准入、成员、串行锁
│   │   │   ├── message_service.py     # 消息落库、上下文组装、游标分页
│   │   │   ├── moderation.py          # DFA 敏感词
│   │   │   ├── stats_service.py       # 四维聚合、告警
│   │   │   └── audit_service.py
│   │   ├── tasks/                     # scheduler 任务实现
│   │   │   ├── channel_health.py  quota_reconcile.py  pending_refund.py
│   │   │   ├── backup.py  archive.py  cert_check.py  budget_check.py
│   │   └── utils/
│   │       ├── tokens.py              # tiktoken 估算兜底
│   │       ├── pricing.py             # 成本计算
│   │       └── pagination.py          # 游标分页
│   ├── scripts/
│   │   ├── seed.py                    # 创建 admin + 默认 settings + 种子渠道
│   │   ├── rotate_cipher_key.py       # CHANNEL_CIPHER_KEY 轮换迁移
│   │   └── recalc_daily_usage.py      # 对账修复工具
│   ├── tests/
│   │   ├── conftest.py                # clean_state autouse fixture + 工厂
│   │   ├── factories.py
│   │   ├── smoke/test_stack.py        # 第一天必跑
│   │   ├── unit/                      # router / quota / pricing / moderation / timeutil
│   │   ├── integration/               # auth / channels / conversations / rooms / sse / ws / stats
│   │   └── load/locustfile.py
│   ├── requirements.txt               # 三段式精确版本（pip freeze 产出）
│   ├── requirements-dev.txt
│   ├── pytest.ini                     # asyncio_mode=auto
│   └── pyproject.toml                 # ruff + mypy 配置
└── frontend/
    ├── package.json
    ├── vite.config.ts                 # dev 代理 /api → :8000
    ├── tsconfig.json
    ├── index.html
    ├── public/
    │   ├── manifest.webmanifest       # PWA
    │   └── maintenance.html           # L4 静态维护页
    └── src/
        ├── main.ts  App.vue
        ├── router/index.ts            # 路由 + 守卫（meta.requiresAuth/Admin/Membership）
        ├── stores/                    # auth.ts  theme.ts  quota.ts  rooms.ts  chat.ts
        ├── api/                       # client.ts（拦截器/401 处理）+ 各模块封装
        ├── styles/
        │   ├── tokens.css             # 设计令牌（直接来自原型 v6 的 CSS 变量）
        │   ├── themes.css             # data-theme=light/dark
        │   └── base.css
        ├── composables/
        │   ├── useSSE.ts              # 流式接收、断线重连、last_event_id
        │   ├── useRoomSocket.ts       # WS 连接、心跳、增量补齐
        │   └── useTheme.ts
        ├── components/
        │   ├── common/                # NavBar  TabBar  Chip  Avatar  Badge  Switch  Toast  Empty
        │   ├── chat/                  # MessageBubble  MessageActions  StreamingDots  InputBar
        │   ├── room/                  # RoomCard  MemberBar  RoomTopic  JoinDialog
        │   └── admin/                 # ChannelCard  ModelTable  StatCards  Charts
        ├── views/
        │   ├── mobile/                # Login  Msgs  Rooms  Me  Chat  Room
        │   └── admin/                 # Dashboard  Channels  Models  Users  Rooms
        │                              # Invites  Stats  Settings  Audit
        └── utils/                     # format.ts  storage.ts  dompurify.ts
```

---

## 22. 第三方依赖清单

### 22.1 后端 `requirements.txt`

> 版本为兼容约束示例。**脚手架 smoke test 通过后必须用 `pip freeze` 固化为三段式精确版本并提交。**

```
fastapi~=0.115.0
uvicorn[standard]~=0.32.0
sqlalchemy[asyncio]~=2.0.36
asyncpg~=0.30.0
alembic~=1.14.0
pydantic~=2.9.0
pydantic-settings~=2.6.0
openai~=1.55.0
httpx~=0.27.0
redis~=5.2.0
apscheduler~=3.10.5
pyjwt~=2.9.0
argon2-cffi~=23.1.0
cryptography~=43.0.0
structlog~=24.4.0
tiktoken~=0.8.0
python-multipart~=0.0.12
email-validator~=2.2.0
rclone-python~=0.1.0        # 备份上传（或直接调 rclone 二进制）
# dev
pytest~=8.3.0
pytest-asyncio~=0.24.0
respx~=0.21.0
freezegun~=1.5.0
ruff~=0.7.0
mypy~=1.13.0
pip-audit~=2.7.0
```

**特殊说明**：V1 **不引入 litellm**（三协议自研适配器已覆盖需求，见 5.2.1）；V2 若需接入冷门协议再评估，届时必须锁定精确版本并补全适配器测试。`tiktoken` 首次运行需下载 BPE 文件，生产镜像构建时应预热：`RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"`。

### 22.2 前端 `package.json` 核心依赖

```
vue~=3.5.0
vue-router~=4.4.0
pinia~=2.2.0
element-plus~=2.8.0        # 仅桌面管理后台
markdown-it~=14.1.0
dompurify~=3.1.0           # AI 回复 Markdown 渲染前必须过滤
dayjs~=1.11.0
echarts~=5.5.0             # 统计图表
vite~=6.0.0
@vitejs/plugin-vue~=5.1.0
typescript~=5.6.0
# dev
vitest~=2.1.0
@vue/test-utils~=2.4.0
eslint~=9.0.0
```

### 22.3 EOL 关注清单

| 组件 | 关注点 |
|------|-------|
| Python 3.12 | 安全支持至 2028-10，V1 生命周期内无忧 |
| PostgreSQL 16 | 官方支持至 2028-11 |
| Redis 7.2 | 关注许可证变更（Redis 8 改为 RSALv2/SSPL），自建使用不受影响，但升级前确认 |
| Node 20 | 2026-04 结束 LTS，**前端构建镜像应在 W1 前升级到 Node 22 LTS** |
| Vue 3.5 | 活跃维护 |
| Element Plus | 活跃维护，注意与 Vue 小版本的兼容公告 |
| litellm（V2 可选） | 迭代极快、偶有破坏性变更；若 V2 引入必须锁精确版本并跑全量适配器测试 |
| 三协议适配器 | 上游改版风险由「测试连通性」+ 健康巡检发现；预设表与适配器解耦，改版只改预设 |

---

## 23. 生产环境运维手册

### 23.1 日常命令

```bash
alias dc='docker compose -f /opt/ai-chatroom/deploy/docker-compose.yml'

dc ps                                    # 服务状态
dc logs -f --tail=200 app                # 实时日志
dc logs --since=1h app | jq 'select(.level=="ERROR")'   # 近 1 小时错误
dc restart app                           # 重启应用
dc exec app alembic current              # 当前迁移版本
dc exec postgres psql -U $POSTGRES_USER -d ai_chatroom -c "SELECT count(*) FROM messages;"
dc exec redis redis-cli -a $REDIS_PASSWORD INFO memory
bash deploy/scripts/backup.sh            # 手动备份
df -h && du -sh /var/lib/docker/volumes/* # 磁盘
```

### 23.2 故障排查

| 症状 | 排查顺序 |
|------|---------|
| 网页打不开 | `dc ps` → Caddy 日志 → DNS 解析（`dig`）→ 证书状态 → ufw 规则 |
| 能打开但 API 502 | app 容器健康检查 → `dc logs app` → 是否 OOM（`dmesg \| grep -i kill`）→ 迁移是否失败 |
| **AI 不流式、等很久一次性出全文** | **Caddy 未关缓冲**：确认 `@sse` matcher 命中、`flush_interval -1` 生效；再查前端是否用了 `fetch` 而非 `EventSource`/流式读取 |
| AI 报"暂不可用" | 管理端渠道状态 → 是否全部 `auto_disabled` → `dc logs app \| jq 'select(.action=="channel.health")'` → 服务器出网测试 `curl -sS https://api.deepseek.com/v1/models -H "Authorization: Bearer $KEY"` |
| 房间消息收不到 | WebSocket 连接状态（浏览器 Network → WS）→ Redis `PUBSUB CHANNELS` → 是否被 Caddy 超时断开 |
| 额度显示不对 | `daily_usage` 与 `usage_logs` 聚合比对 → Redis 计数是否漂移 → 跑 `python -m scripts.recalc_daily_usage` |
| 有 pending 悬挂 | `SELECT * FROM usage_logs WHERE status='pending' AND created_at < now()-interval '10 min';` → 查 scheduler 是否存活 |
| 数据库慢 | `pg_stat_statements` → 缺索引 → `EXPLAIN ANALYZE` |
| 磁盘满 | 日志轮转是否生效 → Docker 镜像/构建缓存 `docker system prune -af --volumes=false` → 备份文件是否堆积 |

### 23.3 数据恢复

```bash
# 1. 停止写入
dc stop app scheduler
# 2. 下载并解密最近备份
rclone copy r2:ai-chatroom-backup/ /tmp/restore/
gpg --decrypt /tmp/restore/db-20261111-0300.sql.gz.gpg | gunzip > /tmp/restore/db.sql
# 3. 恢复（先建临时库验证，确认无误再替换生产库）
dc exec -T postgres psql -U $POSTGRES_USER -d ai_chatroom_restore < /tmp/restore/db.sql
# 4. 如需恢复到指定时间点，重放 WAL 归档
# 5. 验证行数与最新时间戳，确认后切换
dc start app scheduler
```

**每季度必须做一次完整恢复演练**，记录耗时（用于验证 RTO）。

### 23.4 版本更新与回滚

```bash
# 更新
git fetch --tags && git checkout v1.3.0
dc build app scheduler && dc up -d app scheduler    # 自动跑 alembic upgrade head
curl -s https://your-domain.com/api/health | jq .
# 跑 Smoke Test（见 27.4）

# 回滚
git checkout v1.2.0
dc build app scheduler && dc up -d app scheduler
# 数据库：若本次含迁移，执行 alembic downgrade -1；不可逆迁移则从备份恢复
```

**回滚触发条件（不犹豫）**：任何 P0；Smoke Test 任一项失败；上线 30 分钟内错误率 > 5%。

### 23.5 数据库维护

- 每周日 04:00 `VACUUM ANALYZE`（scheduler 任务）
- 每月检查膨胀：`SELECT * FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;`
- `messages` 超 200 万行时评估分区改造
- 每月 `REINDEX CONCURRENTLY` 高频写入表的索引

### 23.6 磁盘管理

- 应用日志：单文件 100MB 轮转，保留 20 个（约 2GB 上限）
- Caddy 访问日志：50MB 轮转，保留 10 个
- Docker：每月 `docker image prune -af --filter "until=720h"`
- 临时导出 CSV：24 小时后自动清理
- 告警阈值：80% WARN，90% CRITICAL

### 23.7 SSL 证书

Caddy 自动续期。额外每日 06:00 检查：`echo | openssl s_client -servername $DOMAIN $DOMAIN:443 2>/dev/null | openssl x509 -noout -enddate`，剩余 < 30/7/1 天分别告警。

### 23.8 性能基线（上线后第一周记录，作为后续退化对比基准）

| 指标 | 目标基线 |
|------|---------|
| `GET /api/conversations` P50/P95/P99 | 30 / 80 / 150 ms |
| `POST /api/rooms/{id}/messages` P50/P95 | 40 / 150 ms |
| AI 首字 P50/P95 | 700 / 1500 ms |
| AI 完整回复 P50/P95 | 4 / 12 s |
| WS 消息端到端 P95 | < 200 ms |
| 配额扣减 P95 | < 20 ms |
| 容器内存稳态 | app < 400MB，PG < 350MB |

---

## 24. 成本估算

| 项目 | 一次性 | 月度 | 说明 |
|------|-------|------|------|
| 海外 VPS 2核4G40G | — | ¥110-180（$15-25） | 日本/新加坡节点 |
| 域名 | ¥60-100/年 | ≈¥6 | .com |
| SSL 证书 | — | ¥0 | Caddy + Let's Encrypt |
| 对象存储备份 | — | ¥5-10 | R2 出口免费 |
| 可用性监控 | — | ¥0 | UptimeRobot 免费版 |
| 模型 API | — | **¥30-150** | 30 日活、每天 3-8 万 token 估算；有三级预算闸门封顶 |
| 开发工具 | ¥0 | ¥0 | Claude Code 订阅按现有额度 |
| **合计** | **≈¥160-260** | **≈¥150-340** | 全局月预算默认上限 ¥200，超出自动关房间 AI |

**成本失控的三道防线**：用户日 token 上限 → 房间日预算 → 全局月预算。任何一道触发都会自动降级并告警，不依赖人工盯盘。

---

## 25. 并发承载分析表

见 9.1（估算过程）与 9.2（逐操作分析）。核心结论：

- 业务 QPS 极低（< 1 QPS 平均），瓶颈不在计算而在**上游模型延迟**与**长连接数**
- 2核4G 单实例可支撑：30 条 WebSocket 长连接、20 并发 AI 调用（受房间串行限制实际远低于此）、4 TPS 消息写入，余量 > 10 倍
- 真正的硬约束是**成本**而非性能，因此配额与预算闸门是本项目的第一优先级设计
- 扩容路径：加实例（代码已无状态）→ 读写分离（统计查询走副本）→ Redis 集群。三步都不需要改业务代码

---

## 26. CLAUDE.md

见同目录 `CLAUDE.md` 文件（独立交付，供 AI 编程工具作为项目入口读取）。

---

## 27. 上线检查清单

### 27.1 基础设施（8 项）

- [ ] DNS 解析生效（`dig your-domain.com` 返回 VPS IP）
- [ ] SSL 证书正确（浏览器无警告，HTTP 自动 301 到 HTTPS）
- [ ] 防火墙仅开放 22（非默认端口）/ 80 / 443；`nc -zv <ip> 5432` 从外网应失败
- [ ] 种子数据已导入（admin 账号、默认 settings、至少 2 个可用渠道、1 个默认模型）
- [ ] `.env` 全部填齐并与 `.env.example` 逐项比对，无 `__CHANGE_ME__` 残留
- [ ] scheduler 容器运行中且 `replicas=1`，六个周期任务均有执行日志
- [ ] 备份任务已运行**且完成过一次真实恢复验证**
- [ ] 监控告警已配置并**发过一条测试告警确认能收到**

### 27.2 第三方预热（6 项）

- [ ] 各模型账号已实名/开通，Key 已在生产环境跑通连通性测试
- [ ] 各账号 TPM/RPM 限额已记录，确认能支撑预估峰值（30 条 WS + 20 并发 AI）
- [ ] OpenAI 若使用：已养号 ≥ 1 周，Tier 与限额满足需求
- [ ] 对象存储 Bucket 已创建，CORS 与凭证已配置，上传下载各测一次
- [ ] 无 ICP 备案需求（海外部署）✓
- [ ] DNS TTL 已降至 300s（上线稳定 1 周后升回 3600s）

### 27.3 灰度计划（5 项）

- [ ] 阶段 1：自己 + 2-3 人内部测试 1-2 天，跑通全部核心流程
- [ ] 阶段 2：发 10 个邀请码，观察 3 天（重点看配额准确性与成本）
- [ ] 阶段 3：扩到 50 人，观察 2 天
- [ ] 阶段 4：全量（发放剩余邀请码）
- [ ] 灰度监控指标：错误率、AI 首字 P95、上游调用成功率、CPU/内存/磁盘、**每日实际成本 vs 预算**
- [ ] **回退条件**：错误率 > 5% / AI 首字 P95 > 3s / 配额出现任何不一致 / 任何 P0 → 立即回退
- [ ] 灰度放量方式：邀请码发放数量控制（天然灰度）
- [ ] 反馈渠道：建立用户群 + 「我的 → 帮助与反馈」入口

### 27.4 上线后 Smoke Test（5 分钟内完成）

- [ ] 打开首页，HTTPS 无警告，无控制台报错
- [ ] 用 admin 与 member 各登录一次
- [ ] 单聊发一条消息，看到打字机流式效果，收到 `done` 事件，额度数字变化正确
- [ ] 进入房间发一条消息，另一个浏览器窗口能实时收到；@AI 能触发回复
- [ ] 手机端（375 宽）打开，底部三格 tab 对齐、无横向滚动条、图标无方框
- [ ] 管理端打开渠道页，连通性测试返回延迟数字
- [ ] 统计页数字与 `usage_logs` 明细一致

### 27.5 快速回滚（4 项）

- [ ] 触发条件已明确写出（见 27.3）
- [ ] 回滚步骤：`git checkout <上一 tag> && dc build app scheduler && dc up -d app scheduler`
- [ ] 回滚后重跑 Smoke Test
- [ ] 数据库回滚方案：本次若含迁移，`alembic downgrade -1`；不可逆迁移则走备份恢复流程

### 27.6 人工应急（4 项）

- [ ] 应急联系人清单就绪（VPS 工单、各模型平台工单入口、域名控制台）
- [ ] 维护公告与恢复公告模板已存 `docs/runbook.md`，可直接复制发布
- [ ] 通知渠道确定（用户群 + 邮件 + 站内系统通知）
- [ ] 线下兜底：极端情况下可导出全部消息数据分发给用户

### 27.7 上线时间窗口（3 项）

- [ ] 避开周五下午与节假日前
- [ ] 选择工作日上午 10 点，确保后续 4-6 小时有人盯
- [ ] 值守至第一个使用高峰（当晚 20-23 点）过去

### 27.8 上线后第一周每日检查（5 项）

- [ ] ERROR/CRITICAL 日志有无异常增长
- [ ] 有无慢查询出现（`pg_stat_statements`）
- [ ] 磁盘使用趋势（日志、消息表增长）
- [ ] 内存趋势（有无泄漏迹象）
- [ ] **每日模型 API 实际花费 vs 预算**，各渠道成本占比是否合理

---

## 28. 附录

### 28.1 种子数据脚本要点（`scripts/seed.py`）

```
1. 创建 admin 用户（邮箱与初始密码从 env 读取，首次登录强制改密）
2. 写入 settings 默认值：quota / registration / moderation / feature_flags / retention
3. 若 env 提供了种子渠道变量，按【协议类型】创建渠道（enabled）：
   - `SEED_OPENAI_COMPAT_n_*` → `type='openai_compatible'`（可配多个）
   - `SEED_ANTHROPIC_KEY`     → `type='anthropic'`
   - `SEED_GEMINI_KEY`        → `type='gemini'`
4. 创建默认模型注册表（对外名与上游解耦，同一对外名可绑多渠道做 fallback）：
   - smart  (premium, 32k, ¥2.4/¥9.6 每百万 token) → 绑定上游主力模型
   - fast   (fast,    64k, ¥1.0/¥2.0)              → 绑定上游低价模型
   - 设 smart 为 is_default
5. 创建一个示例公开房间「闲聊室」便于首次体验
6. 生成 5 个邀请码打印到控制台（仅一次，不落明文日志）
```

### 28.2 UI 默认方案

- 设计令牌直接取自原型 v6 的 `styles/tokens.css`（黑白灰主体 + `#2E5BFF` 蓝点缀 + 绿/黄/红状态色，4/8/12/16 间距栅格，6/10/14 圆角，11-17px 字号阶梯）
- 白天为默认主题，夜间通过 `data-theme="dark"` 切换，选择持久化到 localStorage
- 图标统一 Material Icons；**新增图标名必须先在浏览器实测渲染宽度等于 font-size**，避免缺字方框撑破布局（原型阶段踩过此坑）
- 所有小字元信息对比度 ≥ 4.5:1

### 28.3 告警规则

| 告警 | 条件 | 级别 | 通知 |
|------|------|------|------|
| 站点不可用 | 健康检查连续 3 次失败 | P0 | 邮件 + 手机推送 |
| 证书即将过期 | 剩余 < 30/7/1 天 | P2 | 邮件 |
| 磁盘 | > 80% / > 90% | P2 / P1 | 邮件 |
| 内存 | 容器 > 90% 限额持续 5 分钟 | P2 | 邮件 |
| 全部渠道不可用 | 可用渠道数 = 0 | P1 | 邮件 + 推送 |
| 单渠道自动禁用 | status → auto_disabled | P2 | 站内 + 邮件 |
| AI 首字延迟 | P95 > 3s 持续 10 分钟 | P2 | 站内 |
| 上游错误率 | 5 分钟窗口 > 20% | P1 | 邮件 + 推送 |
| 房间预算预警 | ratio ≥ 80% | P3 | 站内（房主） |
| 房间预算熔断 | ratio ≥ 100% | P2 | 站内 + 邮件（房主与管理员） |
| 全局月预算 | ≥ 80% / ≥ 100% | P2 / P1 | 邮件 + 推送，100% 自动关房间 AI |
| 用户触发限额 | 单用户单日 ≥ 3 次 | P3 | 站内（管理员） |
| 配额对账不一致 | Redis ↔ DB 差异 > 0 | P1 | 邮件 + 推送 |
| pending 悬挂 | 存在 > 10 分钟的 pending | P2 | 站内 |
| 备份失败 | 任一次失败 | P1 | 邮件 + 推送 |
| 登录暴破 | 同 IP 1 小时内失败 > 50 次 | P2 | 邮件 |

### 28.4 V2 规划（P2 需求，V1 明确不做）

| 功能 | 说明 |
|------|------|
| 文件与图片上传 | 需先做文件头校验、UUID 重命名、对象存储、大小与类型白名单、恶意文件扫描 |
| 语音输入 | 浏览器 MediaRecorder + 上游 ASR |
| 联网检索 | 需接搜索 API，回答附来源，成本与延迟显著上升 |
| 消息编辑与撤回 | 需处理已广播消息的同步撤回 |
| 房间排队入房 | `room_join_requests` 已建表，V1 仅用于审批模式 |
| 会话与房间搜索 | 引入 PostgreSQL 全文检索或 Meilisearch |
| 微信内打开 | 微信 JSSDK + 内置浏览器 SSE 兼容性处理 + 微信授权登录 |
| PWA 离线 / 打包 App | 先做 PWA manifest，再评估 Capacitor |
| 多管理员与 RBAC 细化 | 当前全局角色只有 admin/member |
| 计费与充值 | 若转向对外经营，需接入支付并重新设计状态机与对账 |
| 消息分区与归档自动化 | `messages` 超 200 万行后 |
| 向量检索 / 知识库 | 房间可挂载资料库，pgvector |
| 可观测性升级 | Prometheus + Grafana + OpenTelemetry 全链路追踪 |

### 28.5 交接文档要点

维护人变更时必须交接：

1. 服务器 SSH 访问方式与密钥位置（密码管理器条目名）
2. `.env` 全部密钥的来源与轮换方法（尤其 `CHANNEL_CIPHER_KEY` 的迁移脚本用法）
3. 各模型平台账号的登录方式、当前 Tier/限额、余额与充值方式
4. 域名与 DNS 控制台权限、证书续期机制
5. 备份位置、加密密钥（GPG 私钥）、恢复步骤与最近一次演练记录
6. 本 PRD、`docs/runbook.md`、`docs/postmortems/` 全部历史事故复盘
7. 当前性能基线（23.8）与已知技术债
8. 邀请码发放记录与用户沟通渠道

### 28.6 数据合规说明

- **隐私政策与用户协议**：注册页必须展示并可查阅，明确说明收集哪些数据（邮箱/手机、消息内容、用量数据、IP）、用途、保留期、删除方式
- **数据保留**：消息默认保留 90 天（可配），到期自动删除；用量明细保留 12 个月；审计日志保留 24 个月
- **用户权利**：提供"导出我的数据"（JSON/CSV）与"删除我的账号及数据"入口，删除走 RESTRICT 校验（有房间需先转让或归档）
- **未成年人保护**：注册时声明需年满 14 周岁；内容安全过滤必须开启；不做任何面向未成年人的定向功能
- **AI 生成内容标识**：界面显著位置标注"内容由 AI 生成，仅供参考"；AI 消息在视觉上与人类消息明确区分（左侧蓝条 + AI 标签）
- **数据出境**：服务器部署在海外，若用户主要在中国大陆且收集个人信息，数据出境可能触发相关合规要求。**本项目 V1 为邀请制小范围非经营使用，风险较低；若转为公开面向公众运营，必须在上线前单独评估生成式 AI 服务与数据出境的合规义务，并咨询专业意见。** 本文档不构成法律意见。
- **日志合规**：IP 与操作记录留存用于安全审计，不用于其他目的；禁止在日志中记录消息正文全文

### 28.7 参考资料

本项目模型接入层的设计参考了以下开源项目的成熟实践（借鉴设计思想，非代码依赖）：

- **One API / New API**：渠道（Channel）抽象、模型名重定向映射、权重与优先级路由、失败自动禁用、令牌额度体系、用户→分组→渠道→模型四层结构
- **LiteLLM**：适配器模式（`transform_request` / `transform_response` / `get_supported_openai_params`）、参数白名单、预算预扣先于路由决策、五种路由策略、fallback 与冷却窗口、健康检查驱动路由、call_id 全链路追踪、流式零拷贝透传、多副本下 Redis 状态协同

### 28.8 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.2 | 2026-11-11 | **真实 PostgreSQL 16.15 执行验证**发现并修复：4.2 中 `messages` 外键引用 `usage_logs`，但建表顺序把 `usage_logs` 排在其后，属前向引用，真实建表必然失败（纯语法解析查不出）。已将 `usage_logs` 调整为第 10 张、`messages` 为第 11 张，与 12.3 的 FK 拓扑一致。另补记两条实测陷阱到 12.2。 |
| v1.1 | 2026-11-11 | 按四项决策修订：① 模型接入改为**协议驱动**，新增 5.2.1 协议适配矩阵（三协议的端点/鉴权/系统提示词位置/角色命名/流式分片取值/终止标记/usage 位置/停止原因/参数白名单/错误映射逐项对照）与适配器统一契约，`channels` 增 `preset` 列，适配器目录扩为 6 个文件，V1 移除 litellm；② 管理后台改为**桌面与移动端均完整**，重写 7.2 与 11 章，补两套后台验收标准，里程碑 5 → 6 周；③ VPS 标注待定；④ 域名标注已具备并列明需替换的配置点；⑤ 种子渠道 env 变量按协议重组；⑥ 新增 28.9 决策记录。 |
| v1.0 | 2026-11-11 | 首版，并通过 111 项扫雷审查。修复 7 项 RED：连接池精算错误（2 workers 实为 40 连接）、缺乐观锁 version 列、usage_logs 缺模型/渠道名快照、单聊缺会话级串行与 generation_id、WebSocket 用 query string 传 JWT、users 缺 must_change_password、原型「系统通知」缺数据模型。API 总数经逐端点核算修正为 69（68 REST + 1 WS）。基于原型 v6 与房间流程规格 v2；技术栈经四轮确认（Python+FastAPI+Vue3 / 100 人内单实例 / 海外云 / 移动 H5 + 桌面管理后台）；模型接入层设计参考 One API 与 LiteLLM |

---

### 28.9 v1.1 决策记录（2026-11-11）

| 议题 | 决策 | 影响 |
|------|------|------|
| 模型接入方式 | **协议驱动**：按 openai_compatible / anthropic / gemini 三种协议做通用适配器，填对应类型端点即可接入任意上游 | 新增 5.2.1 协议适配矩阵；`channels` 增 `preset` 列与协议语义注释；适配器目录扩为 6 个文件；V1 移除 litellm 依赖 |
| 管理后台范围 | **桌面 + 移动端均为完整功能** | 重写 7.2 与 11 章；补移动端后台验收标准；里程碑 5 周 → 6 周（W4/W5 拆分） |
| VPS 厂商 | **待定**，部署方案保持厂商中立 | 17.1 标注待定；不阻塞开发，D-5 前确定即可 |
| 域名 | **已具备** | Caddyfile / CORS / CSP 待填实际值；无备案需求 |
| 全局月预算 | 默认 **¥200**（运行时可调，不产生返工） | 无需现在拍板 |
| 消息保留天数 | 默认 **90 天**（运行时可调） | 无需现在拍板 |

**开发前仍需提供（均不阻塞 W1-W3）**

1. 实际域名与子域规划 —— W6 部署前提供，用于填 Caddyfile、CORS、CSP
2. VPS 厂商与地域 —— D-5 前确定，影响采购与延迟实测
3. 首批要接的具体上游与 Key —— W2 联调前提供；建议至少 2 个 `openai_compatible` 渠道以便验证 fallback 与权重路由

---

内容由 AI 生成
