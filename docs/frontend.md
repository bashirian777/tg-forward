# 前端结构与验证

前端使用原生 ES Modules 和 CSS，浏览器直接加载，无需构建步骤。管理界面分为任务、系统资源、设置与操作记录四个视图，当前视图保存在 URL hash 中，支持刷新和浏览器前进／后退。

```text
src/static/
├── index.html          # 登录、导航、主布局和模板入口
├── app.js              # 初始化与刷新调度
├── app.css             # 样式入口
├── js/
│   ├── core.js         # 图标、格式化、共享状态与刷新通知
│   ├── api.js          # 请求、登录状态与认证失效处理
│   ├── ui.js           # 导航、主题、弹窗、焦点与提示
│   ├── tasks.js        # 任务卡片、筛选和操作
│   ├── task-form.js    # 任务创建、编辑与字段依赖
│   ├── task-dialogs.js # 断点与错误记录
│   ├── settings.js     # 运行设置与连接信息
│   └── monitor.js      # 系统资源与操作记录
├── css/                # 基础变量、布局、组件、任务和表单样式
├── views/              # 四个独立视图的 HTML
└── dialogs/            # 各类弹窗的 HTML
```

`src/web_assets.py` 负责组合白名单模板、计算依赖内容版本和重写模块／样式引用。修改公共模块会改变引用它的上层资源版本，防止浏览器混用新旧脚本。静态路由只提供注册的 JS 与 CSS，模板不直接对外提供。新增文件时需要同步更新资源白名单、模板白名单和 `pyproject.toml` 的打包规则。

业务模块在完成写入后调用 `requestRefresh()`，由入口统一调度数据刷新。刷新请求不重叠，隐藏标签页暂停轮询；请求失败保留上次结果并显示提示。任务卡片按 ID 更新，保留已展开的规则与菜单。公共弹窗处理 Escape、Tab 焦点循环、背景交互锁定及关闭后的焦点恢复。

## 验证

资源版本、模板组合、模块可访问性、路径限制和 HTML 元素引用使用 pytest 验证：

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider
```

真实浏览器回归使用 Playwright Core 与本地 Chromium。工具安装在临时目录，不是运行依赖：

```bash
npm install --prefix /tmp/tg-forward-ui-tools playwright-core --no-audit --no-fund
NODE_PATH=/tmp/tg-forward-ui-tools/node_modules node tests/web/check-ui.cjs
```

可通过 `CHROMIUM_PATH` 指定 Chromium 可执行文件，通过 `UI_SCREENSHOT_DIR` 指定截图目录；默认分别为 `/snap/bin/chromium` 和 `/tmp/tg-forward-ui-check`。

脚本自动启动仅提供前端资源的本地临时 Web 服务，全部 API 使用测试数据，不读取线上配置、不连接 Telegram、不修改真实任务。覆盖登录／过期、导航与刷新后恢复、搜索筛选、启动／暂停、编辑与创建、来源变更确认、错误记录、设置提交、刷新失败、键盘焦点与五种屏幕宽度。截图覆盖桌面明暗主题、设置页面与手机布局。
