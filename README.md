# Ursule Bot

Ursule Bot 是一个面向《战舰世界》的单用户、自托管个人助手。项目以三个并列中心组织功能，让活动规划、战绩分析与游戏资讯可以独立演进，同时共享统一的配置、数据库、任务调度和 Web 界面。

当前版本完整承接原“节日船团跟踪器”的能力；战绩中心、信息中心和图片渲染系统已建立可访问、可扩展的骨架，但尚未接入真实业务。

## 三个中心

- **活动规划中心**：奖励目标、资源收入与兑换投入、固定英国轻巡重爬、舰船线路状态、快照、人工修正、同步和日报。
- **战绩中心**：已提供独立模块、服务与页面，后续可加入账号概览、单舰战绩、趋势和周报。
- **信息中心**：已提供独立模块、服务与页面，后续可加入版本公告、活动日历和更新提醒。

应用只读取、计算和提醒，不会自动重置科技树、购船、兑换资源或领取奖励。

## 现有功能

- Wargaming OAuth：读取官方账号和舰船数据，以及私有在港舰船列表。
- 军械库采集：通过 Playwright 登录状态读取资源、活动代币和经济加成卡。
- 第三方数据：以欧服 Account ID 补充账号场次与统计信息。
- 多奖励目标、周期资源收入、资源兑换投入和截止日期预测。
- 英国轻巡固定线路的重爬轮数、经验需求、逐舰进度和时间轴。
- 独立快照及人工修正审计；每天可保留多条快照。
- QQ 官方机器人 `/节日船团` 指令，保留权限、冷却、超时和文字回复协议。
- 每日“同步 → 自动备份 → 通知”，QQ 失败时回退到 SMTP 邮件。
- ZIP 备份导入导出与最近 30 份自动备份保留策略。

## 仓库结构

```text
ursule_bot/
├── __main__.py                 # python -m ursule_bot 入口
├── application.py              # FastAPI 工厂与生命周期
├── core/                       # 配置、数据库、安全、设置、公共模型
├── centers/
│   ├── planning/               # 活动规划计算、查询、同步与快照
│   ├── stats/                  # 战绩中心骨架
│   └── information/            # 信息中心骨架
├── integrations/               # 军械库、Wargaming、第三方、QQ、SMTP
├── interfaces/
│   ├── web/                    # Web 依赖、中间件与分组路由
│   └── qq/                     # 监听器、命令路由与 BotReply
├── jobs/                       # 调度、同步、备份和通知任务
├── rendering/                  # 图片模板、主题、素材与渲染约定
├── templates/                  # Jinja Web 页面
└── static/                     # 分层 CSS 与前端脚本
migrations/                     # Alembic 数据库迁移
tests/
```

依赖方向为 `interfaces → centers → core / integrations`。三个中心彼此不直接导入，外部平台实现只放在 `integrations`。

## 页面与 API

| 页面 | 用途 |
| --- | --- |
| `/` | 三中心门户与系统状态 |
| `/planning` | 活动规划概览 |
| `/planning/goals` | 奖励、预测与资源投入 |
| `/planning/regrind` | 重爬计划与时间轴 |
| `/planning/snapshots` | 快照与人工修正 |
| `/stats` | 战绩中心占位页 |
| `/information` | 信息中心占位页 |
| `/settings` | 系统和集成设置 |

业务 API 使用 `/api/planning/*` 与 `/api/system/*` 命名空间，Wargaming 授权使用 `/auth/wargaming/*`。旧 `/goals`、`/plan`、`/history` 及无命名空间 API 已移除，不提供重定向。

## Windows 启动

要求 Windows 10/11、PowerShell 与 Python 3.12+。

```powershell
Copy-Item .env.example .env
.\scripts\start-windows.ps1
```

脚本会创建 `.venv`、安装依赖并以 `python -m ursule_bot` 启动。访问 <http://127.0.0.1:8000>，首次打开会进入管理员设置页。

开发环境也可手动启动：

```powershell
python -m pip install -e ".[test]"
python -m playwright install chromium
python -m ursule_bot
```

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f ursule-bot
```

容器镜像和发行包名称均为 `wows-ursule-bot`。生产环境建议只通过反向代理暴露服务，并妥善限制 `data/` 目录权限。

## 配置兼容

新配置以 `URSULE_*` 为主，例如：

```dotenv
URSULE_HOST=0.0.0.0
URSULE_PORT=8000
URSULE_DATA_DIR=./data
URSULE_TIMEZONE=Europe/Berlin
```

同名 `TRACKER_*` 环境变量仍可作为回退读取，便于原部署平滑升级。若两者同时存在，以 `URSULE_*` 为准。完整配置见 [.env.example](./.env.example)。

为保证持久数据和旧备份兼容，以下名称刻意保留：

- SQLite 文件：`data/tracker.db`
- 密钥、Cookie 与军械库登录状态文件
- `tracker-*.zip` 备份文件名和备份格式 v1
- 已有安全会话盐及旧 `tracker_session` Cookie 的读取兼容

## 数据库升级与备份

应用启动时自动执行 Alembic：

- 空数据库直接升级到最新版本。
- 没有版本号的旧数据库先执行旧结构规范化，再标记基线。
- 带旧“快照日期唯一约束”的数据库会无损重建快照表，使同一天可保存多条独立快照。
- 恢复 v1 备份后立即执行同一升级流程。

升级前应备份整个 `data/` 目录。Web 设置页仍支持导出和恢复 ZIP；恢复会替换当前数据库，因此只应导入可信备份。

## 扩展新功能

- 活动规则或纯计算：放入 `centers/planning/` 对应模块。
- 外部 API、登录或消息渠道：放入 `integrations/`，由中心服务调用。
- 新页面/API：在 `interfaces/web/routes/` 增加薄路由，业务逻辑保留在中心服务。
- 战绩或资讯功能：分别从 `centers/stats/`、`centers/information/` 扩展，避免中心互相依赖。
- 图片输出：遵循 [rendering/README.md](./ursule_bot/rendering/README.md)，在 `templates/`、`themes/`、`assets/` 中逐步加入模板与素材，再实现渲染器。

## 测试

```powershell
python -m pytest
```

测试覆盖规划算法、采集解析、QQ/SMTP、备份、快照兼容、架构边界、路由和数据库迁移。提交前还应启动应用并检查 `/health`，再分别验证桌面与移动端页面。

## 安全边界

- 单用户、自托管；不提供多用户或角色权限模型。
- 密码使用 Argon2，敏感设置使用本地 Fernet 密钥加密。
- OAuth state、表单 CSRF、同步锁、QQ 权限与冷却逻辑继续生效。
- `.env`、`data/`、数据库、备份和 Cookie 文件不得提交到仓库。
