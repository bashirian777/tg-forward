# Telegram Forwarder

Telegram 图片、视频和相册转发工具，支持论坛话题、内容过滤、断点续传和媒体 ID 去重。通过 Web 控制台管理任务，也可启用 Telegram 管理 Bot。

## 获取项目

```bash
git clone https://github.com/bashirian777/tg-forward.git
cd tg-forward
```

## 配置账号

首次部署创建配置文件：

```bash
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，填写以下配置：

| 配置 | 说明 |
| --- | --- |
| `TG_API_ID`、`TG_API_HASH` | 从 https://my.telegram.org 获取 |
| `TG_PHONE` | 要登录的 Telegram 手机号，包含国家区号，如 `+8613800000000` |
| `WEB_INITIAL_PASSWORD` | 首次 Web 管理密码，已有数据库通过设置页修改 |
| `WEB_HOST` | 监听地址，默认 `0.0.0.0` |
| `WEB_PORT` | Web 端口，默认 `10082` |
| `TG_BOT_TOKEN`、`TG_ADMIN_IDS` | 可选，管理 Bot 的 token 和逗号分隔的管理员 ID |
| `TG_PROXY_URL` | 可选，Telegram 连接代理，支持 socks5、socks4 和 http |

## Docker 部署

需要 Docker Engine 和 Docker Compose v2，在项目目录执行：

```bash
docker compose build
docker compose run --rm forwarder init
docker compose run --rm forwarder login
docker compose up -d
```

`init` 初始化数据库；`login` 在终端输入 Telegram 验证码，开启两步验证的账号还需输入两步验证密码。登录会话会保存，后续启动无需重复登录。

查看日志：

```bash
docker compose logs -f forwarder
```

## 源码部署

支持 Linux，需要 [uv](https://docs.astral.sh/uv/getting-started/installation/)、Node 22.12 及以上和 npm。推荐 Python 3.12，uv 会在需要时自动下载。

在项目根目录执行以下命令，创建并激活环境、安装依赖、构建前端：

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r pyproject.toml
python -m scripts.build_frontend
```

完成上面的[配置账号](#配置账号)步骤，填写 `.env`，然后初始化数据库并登录 Telegram：

```bash
python main.py init
python main.py login
```

`login` 在终端提示输入验证码；开启两步验证时，再输入 Telegram 两步验证密码。密码输入时不会显示字符，出现 `Telegram login completed` 表示登录成功。已有有效会话时无需再次登录。

前台运行：

```bash
python main.py serve
```

日志显示在当前终端，按 `Ctrl+C` 停止。需要后台运行时，先退出前台进程，再执行：

```bash
bash run.sh start
```

脚本会在后台启动；已运行时不会重复启动，关闭终端后仍会运行。日常管理命令：

```bash
bash run.sh stop       # 停止，等待任务和 worker 退出
bash run.sh restart    # 重启
bash run.sh status     # 查看运行状态
```

查看后台日志：

```bash
tail -f data/logs/forwarder.log
```

重新打开终端后，运行 Python 命令前执行 `source .venv/bin/activate`。`run.sh` 自动使用项目的 `.venv`，无需激活。

## 开始使用

部署后在浏览器打开 **`http://服务器IP:10082`**，输入 `.env` 中设置的管理密码。修改 `WEB_PORT` 后使用对应端口访问。

在「任务」页创建任务，填写来源、目标和需要的转发规则，然后点击启动。Telegram 用户账号需要拥有读取来源和发送到目标的权限。服务重启后，任务默认停止，在控制台手动启动即可继续。

支持以下转发设置：

- 来源和目标的论坛话题。
- 随机延迟、关键词过滤、Hashtag 筛选与删除、自定义标题前缀。
- 隐藏转发来源、媒体 ID 去重、标题携带来源话题名。
- 仅转发含视频的消息，混合相册中的图片也会保留。
- 下载、上传 worker 数和媒体组并发数，可在设置页调整。

仅处理图片和视频，纯文本跳过。停止任务会保留断点及未完成的续传资料，再次启动后继续。

## 数据保存

Docker 和源码部署默认都使用项目下的目录：

```text
data/
├── forwarder.db                 # 设置、任务、断点和去重记录
└── sessions/forwarder.session   # Telegram 登录会话
temp/                           # 临时媒体和续传文件
```

更新代码或重建容器会保留这些文件。备份时先停止服务，再复制 `data/`；需要保留续传资料时也复制 `temp/`。

日志、更新、重新登录和复用现有数据的步骤见[部署说明](docs/deployment.md)。开发和测试命令见[开发文档](docs/frontend.md)。

许可证尚未确定，当前仓库尚未授予开源许可。
