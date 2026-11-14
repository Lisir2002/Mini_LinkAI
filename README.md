# Mini_LinkAI · PHP 全量重构版

> **本仓库已做根本性技术栈重构。** 原实现（FastAPI + PostgreSQL 16 + Redis 7 + Caddy/Docker Compose）已整体替换。
> 旧版完整源码备份见 Release 附件 `original-source-backup.zip`，Git 历史中也保留清空前的提交。

多房间 AI 聊天平台：管理员按协议接入模型渠道，成员用邀请码注册后单聊 AI，或进房间与其他人和 AI 一起讨论。

## 技术栈

| 层 | 本版 | 原版 |
|---|---|---|
| 后端 | **PHP 8.1 原生单入口**（无框架、无 Composer） | FastAPI + Uvicorn |
| 数据库 | **MySQL 8.0**（25 张表，PDO 预处理） | PostgreSQL 16 |
| 缓存 / 状态 | MySQL 表 | Redis 7 |
| 前端 | **Vue 3 全局构建 + 原生 HTML/CSS/JS**（零构建工具） | 前端 SPA |
| 实时 | 3 秒增量轮询 | WebSocket 广播 |
| 定时任务 | `bin/scheduler.php`（配 crontab） | APScheduler |
| 部署 | **无容器**，`php -S` 直接跑 | 五服务 Docker Compose |

图标全部为自绘内联 SVG，不依赖图标字体或第三方图标库。

---

## 一、快速启动

### 方式 A：一键启动（推荐）

```bash
git clone https://github.com/Lisir2002/Mini_LinkAI.git
cd Mini_LinkAI
sh start.sh          # 首次自动从 Release 拉取 PHP/MySQL 运行时 → 建库 → 种子 → 起 Web
sh stop.sh           # 停止，数据保留在 .db/data
```

打开 **http://127.0.0.1:8080**

仓库本身不携带二进制；`start.sh` 首次运行会调 `bin/fetch_runtime.sh` 从 GitHub Release 下载 `runtime.tar.gz`（约 56 MB）并解压到 `.runtime/`。运行时自带 PHP 8.1、MySQL 8.0 及全部动态库，通过 `LD_LIBRARY_PATH` 加载，**不依赖系统是否装了 PHP/MySQL，也不需要 Docker**。

端口可用 `PORT=8081 sh start.sh` 修改。若下载失败，会自动回退到方式 B。

### 方式 B：本地已有 PHP + MySQL（phpStudy / 宝塔 / XAMPP）

1. 建库 `linkai`（utf8mb4），导入 `src/schema.sql`
2. 在项目根目录建 `.env.php`：
   ```php
   <?php return [
     'DB_HOST' => '127.0.0.1', 'DB_PORT' => 3306,
     'DB_NAME' => 'linkai', 'DB_USER' => 'root', 'DB_PASS' => '你的密码',
     'JWT_SECRET' => '换成随机长字符串',
     'CHANNEL_CIPHER_KEY' => '换成另一串随机字符串',
     'ENVIRONMENT' => 'production',
   ];
   ```
3. `php bin/migrate.php` 灌种子数据
4. `PHP_CLI_SERVER_WORKERS=16 php -S 0.0.0.0:8080 -t public public/index.php`

> SSE 长连接会占用 PHP 内置服务器 worker，worker 不足时房间 @AI 回调本机上游会互等卡死，故默认给 16。
> 生产环境请用 Nginx/Apache + PHP-FPM，`public/` 为站点根目录，其余目录放在 Web 根之外，反代需 `proxy_buffering off`。

### 演示账号

| 项 | 值 |
|---|---|
| 管理员 | `admin@demo.com` / `AdminPass2026` |
| 首次登录 | **强制改密**（可填同样的密码） |
| 邀请码 | `RM-82B377`、`RM-8D4EB1`、`RM-371B43`、`RM-181C52`、`RM-9626BC` |

已预置「本地 Mock」渠道（`http://127.0.0.1:8080/api/mock/v1`）并绑定 `smart → mock-chat`，**不需要任何真实模型 Key** 就能跑通完整流式对话。

---

## 二、接真实模型厂商

登录 → 我的 → **模型接口配置** → 添加接口：

1. 选协议（OpenAI 兼容 / Anthropic / Gemini），可用厂商预设一键填 Base URL
2. 填真实 API Key（AES-256-GCM 加密存储，只回显末 4 位），保存
3. **测试连通** → **同步模型**
4. 到 **模型注册表** → 给 `smart` 绑定该渠道与上游模型名
5. 回消息页发消息即可，无需改代码

Anthropic 兼容端点（如讯飞星火 MaaS）填 Base URL 时**不要带 `/v1/messages`**，程序会自动拼。鉴权同时发送 `x-api-key` 与 `Authorization: Bearer`；探活优先走 `/v1/models` 取真实模型名，不硬编码 `claude-*`。可用 `bin/setup_xfyun.php` 一键配置：

```bash
XF_API_KEY='你的Key' php bin/setup_xfyun.php
```

---

## 三、功能清单

**成员端（移动优先）**
登录 / 注册（邮箱或手机号 + 邀请码）、首次强制改密、会话列表（搜索 / 置顶 / 删除撤销）、SSE 流式对话（打字机、停止生成、用量显示、模型切换）、房间广场（创建 / 加入 / 搜索）、房间群聊（@AI 触发、成员昵称、3 秒增量轮询）、我的页（用量进度、主题切换、管理入口）、全局搜索、好友与私聊、分享链接、Markdown 导出、消息反馈、Prompt 模板。

**管理端（移动卡片 + 桌面双栏）**
渠道 CRUD（先选协议 → 表单动态渲染 → 厂商预设 → 参数白名单 → 优先级权重 → 连通性测试 → 同步模型 → 启停与最后渠道保护 → 删除影响范围二次确认）、模型注册表（对外名解耦、绑定渠道、设默认、乐观锁）、邀请码（批量生成 / 掩码 / 作废）、系统设置（配额 / 注册方式 / 内容安全 / 特性开关 / 保留天数）、用户管理、统计面板、审计日志、定时兜底。

**后端能力**
三协议适配器、渠道选路（优先级 + 权重 + 冷却跳过 + 鉴权失败立即禁用 + 连续失败自动禁用）、配额原子预扣与结算退回、会话级串行与 generation 防覆盖、JWT + 黑名单 + 改密吊销其他 token、argon2id、渠道 Key 加密只回显末 4 位、审计日志、悬挂订单兜底与渠道健康巡检、幂等键、内容安全词表。

---

## 四、测试与验证脚本

```bash
python3 bin/e2e_check.py       # 28 项 API 全链路 + Chromium 三宽度截图
python3 bin/test_chatrooms.py  # 16 类聊天室测试
python3 bin/layout_audit.py    # 15 页 × 8 宽度 + 抽屉，检测横向溢出
```

需 `playwright` + Chromium。实测结果：API 28/28、聊天室 16/16、布局体检 118 项零越界、控制台零错误。

移动端曾修复一处真实切割：`.list` 单列 grid 未写 `minmax(0,1fr)`，列宽等于最长子项 min-content，320px 下卡片被撑到 672px。详见 `public/app.css` 中的 `min-width:0` / `overflow-x:clip` / `overflow-wrap:anywhere` 防御。

---

## 五、远程部署

`deploy_remote.py` 在**能直连目标服务器**的机器上用 paramiko 运行，默认只做只读探查，加 `--apply` 才执行：

```bash
python3 -m pip install paramiko
export LK_HOST='服务器IP' LK_USER=root LK_PASS='密码' LK_PORT=22
export XF_API_KEY='模型Key'
python3 deploy_remote.py            # 先看清楚服务器上跑的是什么
python3 deploy_remote.py --apply   # 确认后再执行
```

旧源码**移动到** `/root/linkai_trash/<时间戳>/`（可恢复，不做 `rm -rf`）；自动配 nginx 反代（`proxy_buffering off`）、随机密钥 `.env.php`、模型渠道，并跑聊天室测试与布局体检。

脚本不接受硬编码凭据，全部经环境变量传入，且不写入日志。

---

## 六、架构差异与已知限制

| 原实现 | 本版 | 说明 |
|---|---|---|
| PostgreSQL 16 | MySQL 8.0 | 表结构 / 事务 / `ON DUPLICATE KEY` 重写 |
| Redis 7 | 数据库表 | 黑名单、配额、选路冷却全部落库 |
| WebSocket 广播 | 3 秒增量轮询 | PHP 内置服务器无常驻 WS 进程 |
| APScheduler | `bin/scheduler.php` | 线上配 `* * * * * php bin/scheduler.php --once` |
| Fernet | AES-256-GCM | 同为认证加密 |
| Caddy SSE 关缓冲 | PHP `X-Accel-Buffering: no` + `ob_implicit_flush` | 前置反代需关 `proxy_buffering` |
| Pydantic 校验 | 手写白名单 + 类型约束 | 渠道写入字段严格白名单 |

**限制**：PHP 内置服务器仅用于本地学习/演示；房间 AI 冷却 5 秒；上传功能默认关闭；`web_search` / `voice_input` 开关保留但无对应实现。

---

## 七、上线前必改

- 换掉 `.env.php` 的 `JWT_SECRET` / `CHANNEL_CIPHER_KEY`
- 改掉演示管理员密码与 5 个邀请码
- `ENVIRONMENT=production`（避免 500 返回堆栈）
- 用 HTTPS；设 `CORS_ORIGINS` 为具体域名
- 配 crontab 跑 `bin/scheduler.php --once`
- 前置反代关 SSE buffering

---

## 八、目录

```
.
├── start.sh / stop.sh          # 一键启停（自动拉取运行时）
├── README.md
├── deploy_remote.py            # 远程一键部署（默认只读探查）
├── public/                     # Web 根：index.html / index.php / app.css
│   ├── core.js                 # Vue 状态、API、SSE、图标、通用组件
│   ├── views-member.js         # 成员端视图
│   ├── views-admin.js          # 管理端视图
│   ├── app.js                  # 路由与守卫
│   └── vendor/vue.global.prod.js
├── src/
│   ├── schema.sql              # 25 张表
│   ├── config.php / db.php / lib.php
│   ├── upstream.php            # 三协议适配器 + 内置 mock
│   └── handlers_*.php          # auth / admin / chat / rooms / misc
├── bin/
│   ├── migrate.php / scheduler.php / reset_demo.php
│   ├── fetch_runtime.sh        # 从 Release 拉取运行时
│   ├── setup_xfyun.php         # 配置 Anthropic 兼容渠道
│   ├── e2e_check.py / test_chatrooms.py / layout_audit.py
│   └── create_db.php
└── .runtime/                   # 首次启动后生成（不入库）
```
