# 战舰世界节日船团任务跟踪器

面向《战舰世界》欧服账号的单用户、自托管进度面板。应用会汇总节日船团代币、账号资源、稀有经济加成卡、战斗场次和英国轻巡重爬进度，并在每天同步后更新预测和生成备份。

项目支持 Windows 本地预览，以及 Ubuntu ARM64/AMD64 常开主机上的 Docker Compose 部署。它只负责读取、计算和提醒，不会自动重置科技树、购船、兑换资源或领取奖励。

## 当前功能

- Wargaming OAuth：读取官方舰船统计和 `account/info` 的私有 `private.port` 在港舰船列表。
- 军械库采集：通过 Playwright 登录状态读取资源、节日代币和蓝色经济加成卡。
- 第三方战绩：只提交欧服 Account ID，补充账号场次与统计信息。
- 奖励规划：支持多个奖励目标，截止日期统一为 `2027-02-01`。
- 周期资源：可配置一次、每日、每周或每月获得的煤炭、钢铁和研发点。
- 资源投入：先计算截止日前资源总量，再由用户决定投入多少资源兑换活动代币。
- 重爬计划：根据仍缺的研发点计算英国轻巡重爬轮数、总经验和逐舰日期。
- 快照：每天自动更新，也可手动截取并修正资源、加成卡、场次、时间和爬线舰船。
- 审计：手工修改要求填写原因，并保留修改记录。
- 通知：支持 QQ 官方机器人，失败时回退到 SMTP 邮件。
- 备份：网页导出/导入 ZIP；每日同步后自动备份并保留最近 30 份。

## 技术栈

- Python 3.12+
- FastAPI、SQLAlchemy、SQLite、APScheduler
- Jinja2、HTMX、本地 CSS
- Playwright Chromium
- Docker Compose，单 Uvicorn worker

## Windows 快速预览

要求 Windows 10/11、PowerShell 和 Python 3.12 或更高版本。

```powershell
Copy-Item .env.example .env
.\scripts\start-windows.ps1
```

脚本会创建 `.venv`、安装项目依赖并启动服务。随后打开：

<http://127.0.0.1:8000>

首次启动需要创建至少 10 位的本地管理员密码。应用默认仅监听本机，不会直接暴露到局域网或公网。

再次启动可继续使用同一脚本，或者执行：

```powershell
.\.venv\Scripts\python.exe -m tracker
```

## 配置数据源

### 1. Wargaming Application ID 与 OAuth

1. 在 [Wargaming Developer Room](https://developers.wargaming.net/) 创建应用并取得 Application ID。
2. 在“设置”中填写欧服 Account ID 和 Application ID。
3. 点击“授权 Wargaming”，在官方页面完成登录和授权。
4. 返回设置页后点击“立即同步”。

Wargaming 通用 OpenID 登录由 `api.worldoftanks.eu/wot/auth/login/` 承载；授权后的战舰数据仍从 `api.worldofwarships.eu/wows/` 获取。这是官方服务的正常分工。

在港舰船必须通过 `account/info` 的 `extra=private.port` 获取。跟踪器不会把历史战绩舰船误认为当前在港舰船；若 OAuth 未返回该字段，爬线进度会保持不变并显示警告。

### 2. 军械库登录状态

应用不保存你的 Wargaming 账号密码。Windows 上执行：

```powershell
.\scripts\auth-armory.ps1
```

在弹出的 Chromium 中手动登录欧服军械库，确认页面已经显示账号资源，然后返回 PowerShell 按 Enter。登录助手会生成：

```text
data/auth/armory-storage.json
```

本机预览会直接使用该文件。部署到 Linux 时，可从设置页导入它，或安全复制到服务器的 `data/auth/`。该文件包含敏感 Cookie，不要提交到 Git、上传到网盘或分享给他人。

军械库当前读取：

- 银币、达布隆、煤炭、钢铁、研发点、社区代币、全局经验、精英指挥官经验；
- 节日船团代币；
- 蓝色加成卡：银币 `+160%`、战舰经验 `+800%`、指挥官经验 `+800%`、全局经验 `+2400%`。

### 3. 第三方战绩

第三方接口不需要额外密钥，只接收设置中的欧服 Account ID。Wargaming OAuth 令牌、军械库 Cookie 和通知密钥不会发送给第三方。

## 使用流程

### 奖励与资源

1. 在“奖励与资源”添加奖励名称、数量和代币成本。
2. 添加预计资源收入，选择一次、每日、每周或每月周期。
3. 页面会计算截至 `2027-02-01` 的预计资源总量。
4. 手工分配愿意投入兑换的煤炭、钢铁和已有研发点。
5. 剩余代币缺口会换算成额外需要获取的研发点。

兑换按完整区块计算：

| 资源 | 每个区块 | 获得代币 |
|---|---:|---:|
| 煤炭 | 5,000 | 1,500 |
| 钢铁 | 500 | 1,500 |
| 研发点 | 1,000 | 1,500 |

煤炭最多计入 650,000。程序只做规划，不会在游戏内执行兑换。

### 固定重爬线路

当前固定为英国轻巡：利安得 → 斐济 → 爱丁堡 → 涅普顿 → 米诺陶可研发并重置。

| 阶段 | 经验 |
|---|---:|
| 利安得 → 斐济 | 82,000 |
| 斐济 → 爱丁堡 | 126,500 |
| 爱丁堡 → 涅普顿 | 201,000 |
| 涅普顿 → 米诺陶可研发 | 280,000 |
| 每轮合计 | 689,500 |

跟踪器根据研发点差额计算所需轮数，将总经验从计划创建日到截止日按自然日基本均分，再换算出每轮各舰船应完成的日期。它不尝试读取或估算舰船当前经验，实际进度只使用每日在港舰船变化：

- 首次检测到米诺陶消失且利安得出现：第一轮开始；
- 低级舰船消失且更高级舰船出现：到达下一阶段；
- 涅普顿消失且利安得出现：上一轮完成并已立即开始下一轮；
- 米诺陶无需购买，只需攒够研发经验后重置。

同一天重复同步保持幂等，不会重复增加完成轮数。

### 快照与手工修正

“历史”页面提供“立即截取快照”按钮。当天重复截取会更新同一天的记录，不会创建重复日期。

每条快照展示资源、四类蓝色加成卡、累计场次、采集时间、爬线舰船和完成轮数。展开快照后可以修改这些字段；修改最新快照的爬线状态时，也会同步更新当前活动计划。所有修改都需要填写原因并进入审计记录。

## 自动同步与通知

默认每天北京时间 04:00 同步。时间可在 `.env` 中调整：

```dotenv
TRACKER_TIMEZONE=Asia/Shanghai
TRACKER_SYNC_HOUR=4
TRACKER_SYNC_MINUTE=0
```

容器使用一个 Uvicorn worker，避免重复启动定时任务。当天已有快照时，同步会幂等更新该记录；采集失败会记录数据源错误，不会把旧数据伪装成当天新数据。

通知可在设置页配置 QQ 官方机器人或 SMTP 邮件，并分别测试好友和群聊消息。QQ 可同时保存好友 `user_openid` 和群 `group_openid`，两个调用通道互相独立；每日通知可选择仅好友、仅群聊或两者。消息模板支持 `{subject}`（通知标题）和 `{report}`（动态日报正文）；QQ 发送失败时会自动尝试邮件。

机器人同时通过 WebSocket 监听以下严格命令：`/节日船团 进度`、`/节日船团 资源`、`/节日船团 爬线`、`/节日船团 同步` 和 `/节日船团 帮助`。只响应设置中保存的 User/Group OpenID；群聊不能执行同步，同步命令有 5 分钟冷却，重复事件会被丢弃，所有同步入口共享并发锁。QQ 不提供修改设置、导入备份或执行任意代码的能力。

## 备份与恢复

设置页支持：

- “导出 ZIP 备份”：下载当前完整 SQLite 数据；
- “校验并导入备份”：校验格式、版本、数据库完整性和必要数据表后恢复；
- 导入前安全备份：恢复前自动保存当前数据库，便于回退；
- 自动备份：每日同步提交后生成 `tracker-auto-YYYY-MM-DD.zip`，保留最近 30 份。

备份包含目标、资源、快照、计划和应用设置，因此可能包含 Wargaming OAuth 令牌及通知密钥，应按敏感文件保管。备份不会包含 `data/auth/armory-storage.json`；迁移设备后需要单独重新导入军械库登录状态。

## Ubuntu ARM64 / AMD64 部署

要求 Ubuntu 22.04/24.04、Docker Engine 和 Docker Compose 插件。

```bash
cp .env.example .env
mkdir -p data/auth data/backups
sudo chown -R 10001:10001 data
docker compose up -d --build
```

Compose 默认只把服务绑定到服务器的 `127.0.0.1:8000`。从 Windows 通过 SSH 隧道访问：

```bash
ssh -L 8000:127.0.0.1:8000 user@your-server
```

然后在 Windows 浏览器打开 <http://127.0.0.1:8000>。

常用命令：

```bash
docker compose ps
docker compose logs -f app
docker compose up -d --build
docker compose restart app
```

将 Windows 生成的 `armory-storage.json` 导入 Linux 后，确保 `data/` 仍可由容器内 UID `10001` 读写。不要复制整个 Chromium 用户目录。

## 数据目录

```text
data/
├── tracker.db                 # SQLite 主数据库
├── session.key                # 本地管理员会话签名密钥
├── auth/
│   └── armory-storage.json    # 军械库登录状态，不进入 ZIP 数据备份
└── backups/
    └── tracker-*.zip          # 自动、手工及导入前安全备份
```

`.env`、`.venv/` 和整个 `data/` 已排除版本控制。

## 常见问题

### OAuth 返回 `METHOD_NOT_FOUND`

不要手工访问 `/wows/auth/login/`。请从设置页点击“授权 Wargaming”；项目使用正确的通用登录入口 `/wot/auth/login/`。

### OAuth 成功但没有 `private.port`

确认授权账号与设置中的欧服 Account ID 一致，然后重新授权。当前采集器会使用 `extra=private.port`；如果令牌过期、会话被撤销或账号区域错误，数据源状态会显示提示。

### 军械库资源或加成卡为空

重新执行 `scripts/auth-armory.ps1`，确认弹出的军械库页面已经加载出你的资源后再按 Enter。若军械库改版导致无法捕获 `inventory` 或 `account/info`，旧数据会保留，数据源状态会记录错误。

### OAuth 回调地址错误

本机预览保持：

```dotenv
TRACKER_PUBLIC_BASE_URL=http://127.0.0.1:8000
```

如果通过其他主机名或反向代理访问，需要把它改成浏览器实际可访问的基地址，并在 Wargaming 应用配置中允许相应回调地址。

### Docker 启动后无法写入数据

```bash
sudo chown -R 10001:10001 data
docker compose restart app
```

## 项目结构

```text
tracker/                 # FastAPI 应用、采集器、规划器、模板和静态资源
tests/                   # 规划、采集、Wargaming 和备份测试
scripts/
├── start-windows.ps1    # Windows 本地启动
├── auth-armory.ps1      # Windows 军械库登录助手
└── backup-linux.sh      # 停机式完整目录备份脚本
Dockerfile               # Playwright Python 运行镜像
compose.yaml             # 单服务、自重启、健康检查和持久目录
.env.example             # 非敏感环境变量模板
```

## 测试

Windows：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Linux / 容器：

```bash
python -m pytest -q
```

当前测试覆盖资源兑换区块、周期资源、研发点与重爬计算、在港舰船状态转换、重复同步幂等性、军械库映射、第三方响应以及备份往返和异常文件拒绝。

## 安全与维护边界

- 默认仅监听本机或服务器回环地址；如需公网访问，请配置 HTTPS 反向代理和访问控制。
- 不要提交或分享 `.env`、`data/`、OAuth 令牌、Cookie、通知密钥和备份 ZIP。
- 军械库使用的是网站内部接口，字段和登录流程可能变化；重新登录和更新映射属于正常维护场景。
- Wargaming、军械库或第三方接口部分失败时，其余数据源仍可继续更新。
- 项目不会代表用户执行任何游戏内资产操作。
