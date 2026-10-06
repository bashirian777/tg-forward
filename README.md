# Telegram Forwarder

Telegram 图片、视频和相册转发工具，支持论坛话题、过滤、断点续传和媒体 ID 去重。用户账号执行转发，Web 控制台与可选的管理 Bot 共用任务管理器。

Web 使用 Vue 3、TypeScript 和 Vite，后端使用 Flask 与 Waitress。生产部署由一个 Python 进程、一个端口提供 API 和前端 dist，运行时不需要 Node。

## 安装与首次启动

### Docker Compose（推荐）

首次部署先准备配置文件：

```bash
cp .env.example .env
chmod 600 .env
```

需要 Docker Engine 和 Docker Compose v2。在 `.env` 中填写从 https://my.telegram.org 获取的 `TG_API_ID`、`TG_API_HASH`、国际格式手机号 `TG_PHONE` 和首次管理密码 `WEB_INITIAL_PASSWORD`，然后在项目目录执行：

```bash
docker compose build
docker compose run --rm forwarder init
docker compose run --rm forwarder login
docker compose up -d
```

`login` 交互输入 Telegram 验证码与两步验证密码。访问 `http://127.0.0.1:10082`，使用 `docker compose logs -f forwarder` 查看日志。数据库和 Telegram 会话保存在项目的 `data/`，临时续传文件保存在 `temp/`，可直接在宿主机查看和备份。Docker 部署无需在宿主机安装 Python 或 Node，配置和更新方式见[部署说明](docs/deployment.md#docker-compose)。

### 从源码运行

目前支持 Linux，Python 3.9 及以上，推荐 Python 3.12。安装与前端构建需要 Node 22.12 及以上和 npm；前端构建完成后，运行服务只需 Python。

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m scripts.build_frontend
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，填写从 https://my.telegram.org 获取的 `TG_API_ID`、`TG_API_HASH` 和国际格式手机号 `TG_PHONE`。填写 `WEB_INITIAL_PASSWORD` 设置首次管理密码。Bot 可选：配置 `TG_BOT_TOKEN` 时同时填写逗号分隔的 `TG_ADMIN_IDS`。

```bash
.venv/bin/tg-forward init
.venv/bin/tg-forward login
.venv/bin/tg-forward serve
```

访问 `http://127.0.0.1:10082`。`login` 交互输入验证码与两步验证密码；已有会话必须属于 `TG_PHONE`。`init` 重复执行保留现有设置、任务和断点。服务启动后任务默认停止，请在控制台手动启动。

## 配置归属

启动参数从系统环境变量、`.env`、默认值依次读取，修改后重启。运行设置和转发状态以 SQLite 为唯一来源。

| 启动参数 | 默认值 / 用途 |
| --- | --- |
| `TG_API_ID`、`TG_API_HASH`、`TG_PHONE` | 必填，Telegram 用户账号 |
| `TG_BOT_TOKEN`、`TG_ADMIN_IDS` | 可选，管理 Bot 和管理员 |
| `DB_PATH` | `data/forwarder.db` |
| `SESSION_PATH` | `data/sessions/forwarder.session` |
| `WEB_HOST`、`WEB_PORT` | `127.0.0.1`、`10082` |
| `WEB_TRUSTED_PROXY` | 可选，单个 HTTPS 反向代理 IP |
| `TG_PROXY_URL` | 可选，`socks5://`、`socks4://` 或 `http://` |
| `WEB_INITIAL_PASSWORD` | 仅首次 `init` 使用 |

源码运行时，相对路径按项目根目录解析，改变 shell 工作目录不会切换数据源。`--env-file /absolute/path/.env` 指定环境文件，但不改变相对数据路径的基准。中文、引号、`#` 等字符可使用 dotenv 引号语法，`${NAME}` 按原文读取。Docker 部署的路径和监听参数由 `compose.yaml` 固定，其他启动参数从 `.env` 注入。

后台展示启动参数来源和连接状态，API Hash、手机号、Bot token、代理凭据只显示是否配置，不回显内容。

| SQLite 运行设置 | 默认值 |
| --- | --- |
| 临时目录 `temp_dir` | 工作目录下的 `temp` |
| 临时文件保留周期 `temp_max_age_hours` | 24 小时；0 禁用自动过期清理 |
| 磁盘保留空间 `min_free_disk_mb` | 1024 MB |
| 并发媒体组 `max_concurrent_tasks` | 1 |
| 下载 / 上传分块 worker | 各 4，范围 1～16 |
| 登录有效期 `web_auth_ttl_hours` | 24 小时 |
| 管理密码 `web_password` | 首次初始化提供的密码 |

登录设置可随时修改，传输参数需要停止全部任务后修改。版本冲突时表单合并最新版本：保留自己的修改、更新未编辑的字段；双方改了同一字段时展示差异并要求明确选择。修改密码或重启服务撤销旧会话；修改有效期只影响新登录，轮询不延长登录。密码以带盐哈希保存，浏览器使用 HttpOnly Cookie 和写请求 CSRF 校验。未设置密码时自动建立本地会话，可在设置页补设密码。

运行文件默认布局：

```text
data/
├── forwarder.db
├── sessions/forwarder.session
├── run/forwarder.pid           # restart.sh 使用
└── logs/forwarder.log          # restart.sh 使用
```

CLI 会话锁按实际 session 文件防止登录和服务同时占用 Telegram 用户会话。CLI 新建、删除任务需先停止服务；在线管理通过 Web 或 Bot 操作。Bot 使用内存会话。

## 管理与转发

控制台包含任务、资源、设置和操作记录四个页面，支持明暗主题及移动设备。任务列表提供「手动顺序 / 最近转发」，排序模式和手动位置由服务器保存；手动模式在全部任务且无搜索时可通过「更多」中的上移 / 下移调整，运行中的任务也可移动。最近转发按成功转发时间从新到旧排列，无记录放在末尾，切回手动顺序会恢复原来的位置。Bot 提供 `/start`、`/list`、`/add`、`/status` 与任务按钮。

```bash
.venv/bin/tg-forward add daily --source -1001234567890 --target -1009876543210 --source-topic 456 --min-delay 10 --max-delay 20
.venv/bin/tg-forward list
.venv/bin/tg-forward verify-db
.venv/bin/tg-forward start daily
```

任务 ID 使用 1～48 位字母、数字、下划线或短横线。来源、目标必须不同；更换来源频道或话题必须指定新断点及是否清空去重。禁用任务先启用，运行中的任务先停止才能编辑。停止取消传输并等待 worker 退出，保留断点和续传资料，再次启动后从断点继续。

任务开关「标题携带来源话题名」默认关闭，开启后按「自定义前缀 #话题名 原标题」发送媒体说明。仅在隐藏转发来源时可用；普通频道 / 群组没有话题时保持原说明，论坛来源包含 General。CLI 创建可加 `--include-topic-name`，Web 表单和 Bot 创建向导也提供开关。

仅处理图片和视频，纯文本跳过。任务开关「仅转发含视频的消息」默认关闭；开启后跳过单张图片及纯图片相册，单条视频及包含视频的混合相册会转发，混合相册中的图片也保留，媒体 ID 去重仍按原规则执行。CLI 创建任务可加 `--require-video`，Web 编辑和 Bot 创建向导也提供该开关。跳过的图片正常推进断点，关闭开关不会自动补发之前跳过的图片。

支持随机延迟、关键词过滤、完整 hashtag 匹配与删除、描述前缀、来源 / 目标论坛话题。媒体 ID 去重识别同一 Telegram 媒体，重新上传的相同内容可能具有新 ID。

隐藏来源时复制媒体，指定复制限制或引用错误可回退到下载上传；显示来源时使用原生转发，不能同时修改描述或发送身份。发送和频道身份权限属于登录的用户账号。

下载、上传使用 512 KiB 分块和有界 worker。隐藏来源的回退下载链路按「最大并发媒体组」并行；每条链路按自己的当前文件检查磁盘预留，同盘多链路时建议调大最低剩余磁盘。下载续传检查 SHA-256 并补齐损坏块；上传保留文件身份和完成分块；发送请求持久化 `random_id` 和回执。分页边界相册补齐后处理，断点只越过已完成消息。服务端去重不能保证无限期 exactly-once。

失败或停止保留有归属的续传资料；成功后清理。跳过、删除与手动清理处理任务目录并排除活动传输。启动时及每 10 分钟清理过期目录。资源页显示临时目录所在磁盘空间。视频封面与缩略图使用 Pillow，无需 ffmpeg。

## 升级、开发与验证

已有 `.env`、SQLite 数据库及 Telegram 会话可继续使用。首次启动新版本自动迁移旧明文管理密码，并清理历史密码字段；旧配置仍包含部署字段的安装先执行 `migrate-env`。升级前停止旧服务，按[部署说明](docs/deployment.md)操作。

```bash
make install       # 安装 Python 开发依赖和锁定的 Node 依赖
make frontend      # 构建前端并复制到后端静态目录
make check         # Python 回归、前端类型和 Shell 语法检查
npm --prefix frontend run test:browser-install
make ui-test       # 离线浏览器回归
```

`make dev` 启动 Vite，后端另用 `.venv/bin/tg-forward serve`。更多命令可运行 `make help` 查看。

开发和浏览器测试说明见[前端文档](docs/frontend.md)。自动检查使用临时数据库和模拟 Telegram，不需要真实账号。

许可证尚未确定，当前仓库尚未授予开源许可。
