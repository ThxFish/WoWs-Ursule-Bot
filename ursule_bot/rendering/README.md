# 图片渲染

当前提供四套互相独立的 PNG 渲染器：

- `kokomi.py`：战绩中心 Kokomi V4 风格长图。
- `activity.py`：活动追踪扁平化长图，消费 `ActivityReport`，也可用 `render_activity_overview()` 从规划中心概览生成。
- `information.py`：信息中心扁平化新闻列表，消费 `NewsItem`；缩略图未下载时自动生成来源占位图。运行时从官网与开发者博客读取最近 7 日内容，按发布时间倒序最多展示 8 条，标题与图片保持原文。
- `daily.py`：日报扁平化长图，依次展示账号活动资源与下一爬线 checkpoint、昨日战绩，以及最近 2 条新闻。

目录职责：

- `templates/`：Jinja2 HTML 卡片模板，只消费报告 ViewModel。
- `themes/`：主题变量、字体声明与 manifest，不包含业务计算。
- `assets/`：背景、图标、舰船等授权静态素材。

渲染器只返回 PNG 字节，由 QQ 接口的 `BotReply.image` 或 Web `Response` 承载；模板不得查询数据库或直接调用采集器。信息中心每张图最多放 8 条新闻，列表高度会随条数变化。
