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

任务列表按内容区可用宽度自动布局：达到 860 像素时显示两列，否则显示单列。卡片中的指标随卡片宽度调整为四列或两列，资源卡片按空间排列，桌面表单的行为开关使用两列。页面、卡片和表单采用紧凑间距，触屏交互控件保留至少 40 像素高度。

任务开关「标题携带来源话题名」默认关闭，开启后按「自定义前缀 话题名 原标题」生成媒体说明，话题名称不添加括号；仅在隐藏转发来源时可用。来源为论坛群组时读取消息所属话题当前名称，General 使用默认话题的实际名称；普通频道 / 群组不插入。名称缓存 5 分钟，读取失败缓存 1 分钟并正常发送原说明；加入名称后超出 Telegram 说明长度限制时保留原说明。单条和相册、复制和下载发送使用同一说明，话题名按普通文字插入，不解析名称中的 Markdown；可靠重试保存第一次发送的说明，避免改名改变重试内容。CLI 创建可加 `--include-topic-name`，Bot 创建向导也提供该开关。

任务列表提供「手动顺序 / 最近转发」，模式和手动位置保存在服务器，各浏览器共享。手动模式下，在全部任务且无搜索时可通过「更多」中的上移 / 下移交换相邻任务；运行中也允许移动，首尾禁用对应方向，保存期间禁止重复移动。新任务追加到手动顺序末尾。最近转发按最后成功转发时间从新到旧排列，无记录放在末尾，同时间沿用手动顺序，每次任务轮询更新；切回手动恢复之前的顺序。排序不改变任务配置版本、断点或调度。`GET /api/tasks?view=1` 同时返回任务数组和 `sort_mode`，原 `GET /api/tasks` 保留数组响应；`PUT /api/task-order` 保存模式，`POST /api/tasks/<task_id>/move` 提交 `up / down`，不使用排序版本。

任务提交中的状态保存在 Pinia，轮询不能恢复按钮点击。顶部手动刷新按钮在当前页面与连接状态请求完成前旋转并禁用重复点击，自动轮询不触发该动画；正在进行的轮询结束后可补一次刷新，切页取消旧请求或请求失败都会释放刷新状态。表单拒绝来源与目标相同，禁止运行中编辑，任务控制仅提供启动 / 停止，停止后保留断点和续传资料，并协调来源展示、前缀、标签删除与发送身份。来源变更需要确认及新断点选项；「仅转发含视频的消息」默认关闭，开启时保留含视频的完整媒体组，跳过纯图片。版本冲突后用编辑基线、当前输入、最新服务器值三方合并：未修改字段采用最新值，自己的独立修改保留，双方修改同字段时展示三份值并要求选择后才能保存。关键词和 Hashtag 文本框同步合并结果，来源重置以最新来源为基线。密码原文不可读取，冲突恢复时已有密码输入需要明确选择保留或放弃。Vue 文本绑定展示错误与文件名，避免字符串 HTML 插入。原生 dialog 提供模态行为，Tab 焦点循环和 Escape 关闭由公共组件管理。

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

Playwright 先启动本地静态测试服务器并模拟 API，验证交互和布局；再启动真实 Flask / RuntimeBridge / SQLite 离线服务器，验证浏览器请求契约。两者都不使用真实 `.env`、Telegram 会话或任务。真实 API 服务器使用临时数据库，禁用 Telegram / Bot 连接 worker，独立监听 18083；静态服务器监听 18082。

测试覆盖登录 / 过期、四页路由、任务操作与禁用状态、表单 / 来源确认、三方合并、同字段选择、连续冲突、设置、磁盘提示、刷新失败、任务排序保存 / 恢复 / 失败以及弹窗键盘焦点。真实 API 场景覆盖排序跨页面同步、设置并发保存、来源变化后 409 优先级、标签同步、新断点、创建删除以及离线启动返回 503。1440、1024、768、390、360 像素宽度分别检查四页面溢出和明暗主题截图。

截图、失败 trace、上下文分别保存到 `frontend/test-results/ui` 与 `frontend/test-results/contract`，均不提交 Git。`npm test` 依次执行两套验证。修改 API 行为时同时更新 Python HTTP 测试和前端类型，必要时更新浏览器模拟接口及真实契约检查。
