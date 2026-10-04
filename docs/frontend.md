# 前端开发与单端口交付

前端为 Vue 3 + TypeScript + Vite，使用 Vue Router history 路由、Pinia 状态和原生 fetch。四个页面为 `/tasks`、`/resources`、`/settings`、`/activity`，前端源码不再位于 Python 包的 static 目录。

```text
frontend/
├── src/
│   ├── api/                 # Cookie / CSRF、错误、慢操作轮询
│   ├── types/               # API 数据类型
│   ├── router/              # 四个页面路由
│   ├── stores/              # 登录、页面数据、操作状态、确认框
│   ├── composables/         # 页面轮询和请求取消
│   ├── layouts/             # 导航、主题、连接状态
│   ├── views/               # 任务、资源、设置、记录
│   ├── components/common/   # 图标、登录、弹窗、设置表单
│   ├── components/tasks/    # 任务卡片、表单、进度、断点、错误
│   └── styles/
├── tests/ui.spec.ts
├── package-lock.json
└── vite.config.ts
```

## 开发

需要 Node 22.12 及以上。先安装 Python 开发依赖，配置 `.env` 并初始化数据库，然后启动后端：

```bash
make install
.venv/bin/tg-forward init
.venv/bin/tg-forward serve
```

另一个终端运行 `make dev`，访问 Vite 的 `http://127.0.0.1:5173`。开发时 Vite 代理 `/api` 至 `127.0.0.1:10082`，保留浏览器 Host。若后端端口不同，在 `frontend/vite.config.ts` 调整代理。开发使用两个端口，生产只运行 Flask / Waitress。

前端登录不保存 Bearer token。HttpOnly Cookie 由服务管理，CSRF token 只在内存中使用。会话变更后拒绝旧响应，离开页面或隐藏页面取消轮询；恢复可见时立即刷新。任务每 5 秒、资源每 10 秒、连接状态每 15 秒刷新；设置按需读取，记录每 15 秒刷新。失败保留最后一次数据并提示。

任务提交中的状态保存在 Pinia，轮询不能恢复按钮点击。表单拒绝来源与目标相同，禁止运行 / 暂停中编辑，并协调来源展示、前缀、标签删除与发送身份。来源变更需要确认及新断点选项，409 冲突保留输入。Vue 文本绑定展示错误与文件名，避免字符串 HTML 插入。原生 dialog 提供模态行为，Tab 焦点循环和 Escape 关闭由公共组件管理。

## 构建与发布

```bash
make frontend       # 构建 frontend/dist，并复制到 Python 包
make build          # 安装锁定的 Node 依赖、构建、生成 sdist / wheel
```

发布脚本将 `frontend/dist` 复制到 `src/tg_forwarder/web/dist`。wheel 包含这些资源；dist 为生成产物，不提交 Git。仅运行 `npm --prefix frontend run build` 不会更新 Python 包中的副本，服务源码时使用 `make frontend`。

Flask 提供 SPA 入口和 `/assets/*`：带内容哈希的资源缓存一年并标为 immutable，`index.html` 和 API 使用 no-store。未知 API、缺失静态文件及未声明页面返回 404，不会返回 HTML 冒充 JS。API 统一使用 `error`、`message`、可选 `fields`，区分输入错误 400、未认证 401、来源 / CSRF 403、缺失 404、状态或版本冲突 409、内部错误 500、Telegram 不可用 503。超时业务不取消，202 返回 operation ID，前端轮询至完成。

## 浏览器回归

```bash
npm --prefix frontend ci
npm --prefix frontend run test:browser-install
make ui-test
# 使用已有 Chromium 时可指定：
CHROMIUM_PATH=/path/to/chromium make ui-test
```

Playwright 启动本地静态测试服务器并模拟全部 API，不使用真实 `.env`、Telegram 会话或任务。测试覆盖登录 / 过期、四页路由、任务操作与禁用状态、表单 / 来源确认、409 保留输入、设置、磁盘提示、刷新失败以及弹窗键盘焦点。1440、1024、768、390、360 像素宽度分别检查四页面溢出和明暗主题截图。

截图、失败 trace、上下文保存到 `frontend/test-results`，均不提交 Git。修改 API 行为时同时更新 Python HTTP 测试和前端类型，必要时更新浏览器模拟接口。
