# Telegram Forwarder

Telegram 图片、视频和相册转发工具。用户账号负责转发，Web 与可选的 Bot 负责管理，支持论坛话题、过滤、断点和并行传输。

## 安装与首次启动

Python 3.9 或更新版本，推荐 Python 3.12。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

编辑 `.env`：从 https://my.telegram.org 获取 `TG_API_ID`、`TG_API_HASH`，填写国际格式手机号 `TG_PHONE`。需要 Bot 管理时，从 @BotFather 获取 `TG_BOT_TOKEN` 并填写 `TG_ADMIN_IDS`，多个管理员用英文逗号分隔。填写 `WEB_INITIAL_PASSWORD` 可设置首次 Web 管理密码。

```bash
.venv/bin/python -m src.main init
.venv/bin/python -m src.main login
.venv/bin/python -m src.main serve
```

`init` 只创建 SQLite 默认设置；重复执行保留现有密码、任务和断点。`login` 交互输入验证码及两步验证密码，不保存这些输入。已有会话必须属于 `TG_PHONE`；更换账号时，先停止服务，再执行 `login --relogin` 明确退出旧会话并登录新账号。更换账号后，启动任务前检查其来源、目标权限及断点。

后台默认地址是 `http://127.0.0.1:10082`，可通过本机、SSH 隧道或现有反向代理访问。Web 先启动，Telegram 未登录、连接失败或 Bot 配置错误时仍可查看状态和修改运行设置。任务启动前检查用户连接，Bot 与 Web 共用一个任务管理器。`bot` 命令是 `serve` 的兼容别名。

服务启动后任务默认停止，由管理员手动启动。登录／转发／测速进程使用同一个会话锁，避免同时占用 Telegram 会话。CLI 删除任务需先停止服务；服务运行时通过 Web 或 Bot 删除。

运行文件集中在 `data/`，目录会自动创建，且不提交 Git：

```text
data/
├── sessions/                       # Telegram 用户会话、会话锁及 SQLite 附属文件
├── run/forwarder.pid                # restart.sh 管理的服务进程
└── logs/forwarder.log               # 后台启动与运行日志
```

Bot 使用内存会话，不生成新的 Bot session 文件。已有根目录会话的安装需要先停止服务，将会话及 `-journal`／`-wal`／`-shm`／`.lock` 附属文件一起移动到新目录，再修改 `.env` 的 `SESSION_PATH`；不要仅修改路径，否则会创建新会话并要求重新登录。具体步骤见 [部署说明](docs/deployment.md#整理旧运行文件)。

## 配置归属

每项设置只有一个来源，启动参数与运行设置使用不同模型和保存接口。

| 启动参数 | 默认／用途 |
| --- | --- |
| `TG_API_ID`、`TG_API_HASH`、`TG_PHONE` | 必填，Telegram 用户账号 |
| `TG_BOT_TOKEN`、`TG_ADMIN_IDS` | 可选，配置 token 时必须指定管理员 |
| `DB_PATH` | `config/forwarder.db` |
| `SESSION_PATH` | `data/sessions/forwarder.session` |
| `WEB_HOST`、`WEB_PORT` | `127.0.0.1`、`10082` |
| `TG_PROXY_URL` | 可选，支持 `socks5://`、`socks4://`、`http://` |
| `WEB_INITIAL_PASSWORD` | 仅第一次 `init` 使用，已有数据库时忽略 |

启动参数优先级：系统环境变量 → `.env` → 默认值。所有相对路径以项目安装目录为基准，改变 shell 工作目录不会切换数据源；可用全局参数 `--env-file /path/to/.env` 指定另一份环境文件。支持带引号的中文及特殊字符值，`${NAME}` 按原文读取，不展开。`.env` 不提交 Git，仓库只提供 `.env.example`。

修改启动参数后需要重启。后台显示参数来源及 Telegram／Bot 状态，Hash、手机号、token 和代理只显示是否配置。端口由 `.env` 管理，后台不提供编辑；启动参数不会写回 SQLite。

`DB_PATH` 指定的 SQLite 保存任务、断点、传输状态、去重、错误、发送回执以及以下运行设置：

| 运行设置 | 默认值 | 修改位置 |
| --- | --- | --- |
| `temp_dir` | 项目目录下的 `temp` | Web |
| `temp_max_age_hours` | 24 | Web；0 禁用自动过期清理 |
| `min_free_disk_mb` | 1024 | Web |
| `max_concurrent_tasks` | 1 | Web；同时处理的媒体组上限 |
| `download_workers`、`upload_workers` | 各 4 | Web；范围 1～16 |
| `web_auth_ttl_hours` | 24 | Web |
| `web_password` | 首次初始化提供的密码 | Web |

运行设置不受环境变量覆盖。登录设置可在任务运行时修改，传输参数需要先停止全部任务。记录级更新和版本检查防止不同入口覆盖彼此的数据；保存失败不改变内存配置。

密码支持中文。登录有效期从成功输入密码开始计算，轮询不延长；修改有效期影响新登录，已有 token 保留原到期时间；修改密码或服务重启撤销已有 token。浏览器保存 token 和到期时间，不保存密码。首次未设密码时，本地后台无需认证，可在后台设置密码。

## 已有安装升级

已有版本的配置和任务已经在 SQLite 中。一次性把部署字段移到 `.env`：

```bash
# 可在旧服务运行时准备 .env，不修改数据库
.venv/bin/python -m src.main migrate-env --prepare
# 停止旧服务后完成迁移
.venv/bin/python -m src.main migrate-env
.venv/bin/python -m src.main serve
```

迁移保留任务、断点、去重、传输、错误和当前 Web 密码，清理数据库配置与历史配置记录中的旧部署字段。已有 `.env` 中的值保留；与旧凭据冲突时列出变量名称并停止，不输出敏感值。迁移不创建归档或历史备份。重复执行完成后的 `migrate-env` 会保留现状。

`restart.sh` 先校验配置，再等待旧服务退出；需要时完成迁移，然后启动 `serve`。旧进程未退出时不会强制杀死或启动第二个实例。指定不存在／未初始化的数据库时，正常启动报错并提示 `init`，不会静默创建空配置。

JSON 配置、自动导入、同步、导出及 JSON 备份功能已移除；配置示例改为 `.env.example`。SQLite 字段、HTTP 数据和临时续传清单可以使用 JSON 序列化，它们不是可编辑的配置文件。

## 管理与转发

Bot 提供 `/start`、`/list`、`/add`、`/status` 和管理按钮。Web 可新建、编辑、启动、暂停、恢复和停止任务。CLI 示例：

```bash
.venv/bin/python -m src.main add daily --source -1001234567890 --target -1009876543210 --source-topic 456 --min-delay 10 --max-delay 20
.venv/bin/python -m src.main list
.venv/bin/python -m src.main verify-db
.venv/bin/python -m src.main start daily
```

`verify-db` 检查 SQLite 完整性及外键。CLI `start` 启动所有 enabled 任务，`start <id>` 启动指定任务。disabled 任务必须先启用。任务 ID 允许 1～48 位字母、数字、下划线或短横线；默认拒绝来源与目标相同。更换来源频道或话题必须明确指定新起点，以及是否清空旧去重。

暂停允许当前文件／媒体组完成，禁止开始下一组；恢复仅适用于暂停的任务；停止取消传输并等待全部 worker 退出，保留有归属的续传资料。

仅处理图片和视频，纯文本跳过。支持随机延迟、关键词、完整 hashtag 匹配与删除、caption 前缀、论坛话题以及 Telegram 媒体 ID 去重。重新上传的相同内容可能有新 ID，这是媒体 ID 去重。

开启隐藏来源时复制媒体，指定复制限制／引用错误可回退到下载上传。关闭时原生转发显示来源，此时不能修改 caption、删除 hashtag 或使用 send-as。实际发送及频道身份权限属于登录的用户账号。

分页边界相册会补齐，实时相册短暂等待稳定；任意必需文件缺失则整组失败。相册穿插其他消息时，断点只越过已完成消息；处理回执避免重发已完成相册。

## 传输与清理

下载上传使用 512 KiB 分块及有界 worker，可设为 1 回退到顺序分块。下载续传验证 SHA-256 并补缺失／损坏块；上传保留文件 ID 和完成分块。已上传引用持久化，最终相册发送失败优先复用，引用过期后重新上传。网络故障退避，FloodWait 按服务端等待，权限等错误等待人工处理。

小磁盘机器建议媒体组并发保持 1。所有下载回退共享一个磁盘名额，主要通过单文件分块并发提速。上传并登记可复用引用后删除源文件。后台显示原始中文文件名，磁盘文件名保持安全、稳定。

工作目录管理媒体、`.part`、封面、缩略图和续传清单。成功后清理；失败／停止保留续传资料；跳过、删除任务和手动清理覆盖对应目录，排除活动传输。启动和每 10 分钟清理过期目录。后台显示实际临时路径和文件占用。

视频封面保留；Pillow 将缩略图规范化为 JPEG，最长边不超过 320 像素、小于 20 KB，无需 ffmpeg。缺少封面时记录警告并继续。

发送请求持久化 random_id 和回执，减少响应丢失带来的重复；服务端去重不能保证无限期 exactly-once。

## 验证

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
for file in src/static/app.js src/static/js/*.js; do node --check "$file"; done
.venv/bin/python -m scripts.benchmark_transfer --size-mb 16 --latency-ms 20
```

前端按视图、业务模块和公共组件拆分，无需构建；目录说明和浏览器回归方法见 [前端文档](docs/frontend.md)。

模拟测速不连接 Telegram，不能当作真实提速承诺。真实测速方法见 [验证记录](docs/verification.md)，服务切换方式见 [部署说明](docs/deployment.md)。
