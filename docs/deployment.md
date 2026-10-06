# 部署与维护

首次安装、配置账号和启动步骤见 [README](../README.md)。部署后访问 `http://服务器IP:10082`。

## Docker 日常操作

在项目目录执行：

```bash
docker compose up -d                 # 启动
docker compose logs -f forwarder     # 查看日志
docker compose restart forwarder    # 重启
docker compose down                 # 停止
```

更新代码后重建并启动：

```bash
docker compose down
git pull
docker compose up -d --build
```

修改 `.env` 后重新创建容器使配置生效：

```bash
docker compose up -d --force-recreate
```

`WEB_HOST` 和 `WEB_PORT` 控制宿主机的监听地址和端口，容器内部使用 `0.0.0.0:10082`。例如在 `.env` 设置 `WEB_PORT=10090`，重建容器后访问 `http://服务器IP:10090`。

## 源码日常操作

激活环境后直接运行源码：

```bash
source .venv/bin/activate
python main.py serve
```

按 `Ctrl+C` 停止。需要后台运行时，先退出前台进程，再使用：

```bash
bash run.sh start       # 后台启动；已运行时不重复启动
bash run.sh stop        # 停止并等待 worker 退出
bash run.sh restart     # 重启
bash run.sh status      # 查看运行状态
```

脚本自动使用项目的 `.venv`，无需激活环境。`restart` 先检查新配置，检查通过后才停止旧进程。后台日志位于 `data/logs/forwarder.log`：

```bash
tail -f data/logs/forwarder.log
```

升级时先停止进程，更新代码和依赖，重新构建前端再启动：

```bash
bash run.sh stop
git pull
source .venv/bin/activate
uv pip install -r pyproject.toml
python -m scripts.build_frontend
bash run.sh start
```

修改 `.env` 后重启服务生效。已有配置中 `WEB_HOST=127.0.0.1` 的安装，如需通过服务器 IP 访问，改为 `WEB_HOST=0.0.0.0`。

## 重新登录 Telegram

已有会话可继续使用。切换账号时，先修改 `.env` 中的 `TG_PHONE`，再停止服务并重新登录。

Docker 部署：

```bash
docker compose stop forwarder
docker compose run --rm forwarder login --relogin
docker compose up -d
```

源码部署：

```bash
bash run.sh stop
source .venv/bin/activate
python main.py login --relogin
bash run.sh start
```

## 数据目录

Docker 将项目的 `./data`、`./temp` 分别挂载到容器的 `/app/data`、`/app/temp`。停止或删除容器会保留宿主机上的目录。

从源码部署切换到 Docker 时，先停止源码服务，保留现有 `.env` 和 `data/`。使用默认路径的数据库和 Telegram 会话会直接复用；临时目录在容器中设置为 `/app/temp`。同一份数据同时只运行一个服务。

`WEB_INITIAL_PASSWORD` 仅在首次初始化时使用，已有密码在 Web 设置页修改。
