# 图片渲染扩展点

图片输出尚未接入运行时。本目录固定后续职责：

- `templates/`：Jinja2 HTML 卡片模板，只消费报告 ViewModel。
- `themes/`：主题变量、字体声明与 manifest，不包含业务计算。
- `assets/`：背景、图标、舰船等授权静态素材。

未来渲染器应返回 PNG/WebP 字节，由 QQ 接口的 `BotReply.image` 承载；模板不得查询数据库或直接调用采集器。
