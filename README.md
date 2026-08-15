# Ursule Bot

面向《战舰世界》的单用户、自托管个人助手。Ursule Bot 将活动规划、个人战绩和游戏资讯集中到一个 Web 控制台，并通过 QQ 官方机器人与邮件完成查询和提醒。

> 当前版本：`0.2.0` · Python 3.12+ · 仅支持欧服账号

## 功能概览

### 活动规划

- 管理多个奖励目标、周期收入、资源投入和截止日期预测
- 跟踪英国轻巡“利安得 → 米诺陶”重爬轮次、逐舰经验和时间轴
- 从 Wargaming API 与军械库同步账号、舰船、资源、代币和经济加成卡
- 保存独立快照与人工修正记录，同一天可保留多次采集结果
- 每日自动同步、ZIP 备份和通知；QQ 失败时回退到 SMTP

### 个人战绩

- 读取唯一配置账号的真实战绩与舰船数据
- 按 WoWS Numbers 逐船期望值计算标准 PR
- 展示总览、战斗类型、舰种、等级分布及查询周期变化
- 生成 Kokomi Bot V4 风格的 `2428 × 4050` PNG，支持亮色和暗色主题
- 本地缓存最近一次结果、近 370 天历史点、舰船期望值和头像素材

### 游戏资讯

- 聚合最近一周的《战舰世界》官网新闻与开发者博客
- 保留标题、摘要、标签、原文地址和缩略图
- 生成资讯图片，并可与活动、昨日战绩组合为日报

应用只读取、计算和提醒，不会自动重置科技树、购买舰船、兑换资源或领取奖励。

## 快速开始

### Windows

要求 Windows 10/11、PowerShell 和 Python 3.12+。双击 `start.bat`，脚本会自动：

1. 从 `.env.example` 创建 `.env`（已有文件不会覆盖）；
2. 创建 `.venv` 并安装项目依赖；
3. 安装 Playwright Chromium；
4. 通过 `python -m ursule_bot` 启动服务。

也可以在 PowerShell 中运行：

```powershell
Copy-Item .env.example .env
.\scripts\start-windows.ps1
```

打开 <http://127.0.0.1:8000>，首次访问会进入管理员初始化页面。

### Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f app
```

Compose 默认只监听宿主机 `127.0.0.1:8000`，持久数据保存在 `./data`。需要远程访问时，建议通过带 HTTPS 的反向代理暴露服务。

## 首次配置

进入“设置与连接”后，按需完成以下项目：

1. 填写欧服 `Account ID` 与 Wargaming `Application ID`；后者可从 Wargaming Developer Room 创建。
2. 可选执行 Wargaming OAuth，以读取私有在港舰船列表。
3. 在有图形桌面的 Windows 环境登录军械库；服务器部署可导入 Playwright `storage_state` 文件。
4. 配置 QQ 官方机器人 `App ID`、`App Secret` 以及允许访问的好友或群 OpenID。群 Group OpenID 可配置多个，每行一个。
5. 配置 SMTP 作为通知通道或 QQ 发送失败时的回退通道。

敏感配置由本地 Fernet 密钥加密后保存在 SQLite 中，不需要写入 `.env`。修改 QQ App ID 或 App Secret 后需重启应用。

## QQ 指令

机器人只响应设置页中列入白名单的好友或群。多个群 Group OpenID 可以换行、逗号、分号或空格分隔；它们不是数字 QQ 群号。自动日报固定只发送给配置的好友 User OpenID，不会主动发送到群聊。中文、英文指令等价。

获取 OpenID 时，先停止正在运行的机器人实例，然后在项目目录执行：

```powershell
$env:QQ_BOT_APP_ID = Read-Host "QQ Bot App ID"
$qqSecret = Read-Host "QQ Bot App Secret" -AsSecureString
$env:QQ_BOT_APP_SECRET = [System.Net.NetworkCredential]::new("", $qqSecret).Password
.\.venv\Scripts\python.exe .\scripts\qq_get_openid.py
```

脚本连接成功后，在每个目标群中分别 `@机器人` 并发送任意文字；终端会打印对应的 `group_openid`。将所有值逐行复制到设置页的“群 Group OpenID”中，保存后重启正式应用。QQ 官方机器人接口使用此 OpenID，不使用群资料中显示的数字 QQ 群号。App Secret 属于敏感凭据，请勿复制到聊天、日志或提交到 Git。

| 功能 | 指令 |
| --- | --- |
| 帮助 | `/帮助`、`/help` |
| 活动状态图 | `/活动`、`/event` |
| 最近新闻图 | `/新闻`、`/news` |
| 个人战绩图 | `/我`、`/me` |
| 绑定兼容战绩账号 | `/绑定 eu 游戏昵称`、`/bind eu 游戏昵称` |
| 近期战绩 | `/近期 参数`、`/recent 参数` |
| 近期随机战绩 | `/随机 参数`、`/random 参数` |
| 近期排位战绩 | `/排位 参数`、`/rank 参数` |
| 单船数据 | `/单船 船名`、`/ship 船名` |
| 舰船筛选 | `/类别 参数`、`/category 参数` |
| 综合日报 | `/日报`、`/daily` |

兼容旧绑定格式 `/wws bind eu 游戏昵称`。兼容战绩查询使用设置中的 Account ID 作为远端用户标识；可通过数据库设置 `kokomi_api_url` 和 `kokomi_api_token` 覆盖默认服务。

监听器带有 OpenID 白名单、重复消息丢弃、频率限制、执行超时和回复长度保护，不提供修改设置、导入备份或执行任意代码的指令。

## 页面与接口

| 路径 | 用途 |
| --- | --- |
| `/` | 三中心门户、数据源和备份状态 |
| `/planning` | 活动资源、目标和进度概览 |
| `/planning/goals` | 奖励目标、周期收入和资源投入 |
| `/planning/regrind` | 英国轻巡重爬计划与时间轴 |
| `/planning/snapshots` | 快照历史与人工修正 |
| `/stats` | 单账号战绩中心与图片预览 |
| `/information` | 最近一周游戏资讯 |
| `/settings` | 账号、集成、通知与备份设置 |
| `/health` | 无需登录的健康检查与版本信息 |

图片接口：

- `GET /api/stats/image?theme=light&refresh=true`
- `GET /api/information/image`

业务写接口使用 `/api/planning/*` 和 `/api/system/*` 命名空间，Wargaming OAuth 使用 `/auth/wargaming/*`。所有非公开页面和接口均受管理员会话保护。

## 环境变量

```dotenv
URSULE_DATA_DIR=./data
URSULE_HOST=127.0.0.1
URSULE_PORT=8000
URSULE_PUBLIC_BASE_URL=http://127.0.0.1:8000
URSULE_TIMEZONE=Asia/Shanghai
URSULE_SYNC_HOUR=4
URSULE_SYNC_MINUTE=0
```

完整示例见 [.env.example](./.env.example)。同名 `TRACKER_*` 变量仍可作为旧部署的兼容回退；两者同时存在时，以 `URSULE_*` 为准。时区及同步时间在进程启动时读取，修改后需重启。

## 数据与备份

运行数据全部位于 `URSULE_DATA_DIR`：

```text
data/
├── tracker.db                  # SQLite 主数据库
├── secret.key / session.key   # 加密与会话密钥
├── auth/                       # 军械库登录状态
├── backups/                    # 自动和手动 ZIP 备份
├── dog_tags/                   # 个人徽章图片缓存
├── ships/expected_pr.json      # 舰船 PR 期望值缓存
├── personal_stats.json         # 最近一次战绩缓存
└── personal_stats_history.json # 战绩历史点
```

应用每天同步后自动备份并保留最近 30 份自动备份。设置页支持手动导出和恢复；恢复会替换当前数据库，请只导入可信文件。军械库 Cookie 不包含在数据库备份中，迁移设备后需要单独重新登录或导入。

应用启动时自动执行 Alembic 迁移，兼容旧 `tracker.db`、v1 备份格式、旧安全会话盐及 `tracker_session` Cookie。升级前仍建议额外复制整个 `data/` 目录。

## 项目结构

```text
ursule_bot/
├── __main__.py                 # python -m ursule_bot
├── application.py              # FastAPI 工厂与生命周期
├── core/                       # 配置、数据库、安全和公共系统模型
├── centers/
│   ├── planning/               # 活动规则、计算、快照与同步编排
│   ├── stats/                  # 战绩模型、采集、缓存与 PR 计算
│   └── information/            # 新闻查询服务
├── integrations/               # 外部 API、认证、采集和通知渠道
├── interfaces/
│   ├── web/                    # Web 路由与依赖
│   └── qq/                     # QQ 监听、命令解析与回复模型
├── jobs/                       # 定时同步、日报和备份
├── rendering/                  # PNG 渲染器、字体、主题和素材
├── templates/                  # Jinja 页面
└── static/                     # CSS 与前端资源
migrations/                     # Alembic 迁移
scripts/                        # 启动、认证和备份脚本
tests/                          # 单元与集成测试
```

依赖方向保持为 `interfaces → centers → core / integrations`。三个业务中心彼此不直接导入；Web 路由只处理协议和展示，采集与业务规则留在中心服务或集成层。图片素材与授权说明见 [渲染模块说明](./ursule_bot/rendering/README.md) 和 [第三方声明](./ursule_bot/rendering/THIRD_PARTY_NOTICES.md)。

## 开发与测试

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ursule_bot
```

测试覆盖规划算法、外部数据解析、战绩与新闻集成、图片渲染、QQ/SMTP、备份、快照兼容、路由边界和数据库迁移。提交前建议同时检查 `/health`、主要页面的桌面/移动布局，以及实际 QQ 图片上传。

新增功能时：

- 纯活动规则和计算放入 `centers/planning/`；
- 战绩或资讯业务分别放入对应中心；
- 外部 API、登录和消息通道放入 `integrations/`；
- Web 路由保持轻量，不直接调用采集器；
- 图片输出遵循 [rendering/README.md](./ursule_bot/rendering/README.md) 的尺寸、素材和授权约定。

## 安全说明

- 本项目面向可信网络中的单用户自托管，不提供多用户或角色权限模型。
- 管理员密码使用 Argon2，敏感设置使用本地 Fernet 密钥加密。
- OAuth state、CSRF、会话校验、同步锁及 QQ 权限与冷却逻辑默认启用。
- `.env`、`data/`、数据库、备份、Cookie 和运行日志不得提交到仓库。
