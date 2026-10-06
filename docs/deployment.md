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

前台运行使用 `.venv/bin/tg-forward serve`，按 `Ctrl+C` 停止。后台运行或重启使用：

```bash
bash restart.sh
```

后台日志位于 `data/logs/forwarder.log`：

```bash
tail -f data/logs/forwarder.log
```

升级时先停止服务，更新代码和依赖，重新构建前端再启动：

```bash
git pull
.venv/bin/pip install -e .
.venv/bin/python -m scripts.build_frontend
bash restart.sh
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

源码部署停止服务后执行：

```bash
.venv/bin/tg-forward login --relogin
bash restart.sh
```

## 数据目录

Docker 将项目的 `./data`、`./temp` 分别挂载到容器的 `/app/data`、`/app/temp`。停止或删除容器会保留宿主机上的目录。

从源码部署切换到 Docker 时，先停止源码服务，保留现有 `.env` 和 `data/`。使用默认路径的数据库和 Telegram 会话会直接复用；临时目录在容器中设置为 `/app/temp`。同一份数据同时只运行一个服务。

`WEB_INITIAL_PASSWORD` 仅在首次初始化时使用，已有密码在 Web 设置页修改。
