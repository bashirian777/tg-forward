# 部署与升级

生产服务运行一个 Python 进程。Waitress 在 `WEB_HOST:WEB_PORT` 提供 Flask API 与 Vue dist，后台线程持有一个长期 asyncio 循环，Telegram 用户客户端、Bot 和任务状态由它管理。不要为同一数据库 / Telegram 会话启动多个 Web worker 或服务副本。

## Docker Compose

需要 Docker Engine 和 Docker Compose v2。镜像构建时使用 Node 编译前端，运行镜像只包含 Python、应用和前端静态资源。镜像自身默认用户为 UID / GID `10001`；Compose 为兼容宿主机目录权限，默认以 `0:0` 运行。使用普通用户管理文件时，可在 `.env` 设置 `DOCKER_UID`、`DOCKER_GID` 为宿主机 `id -u`、`id -g` 的结果，并提前创建该用户可写的 `data/` 和 `temp/`。

首次部署在项目目录复制 `.env.example` 为 `.env`，填写 Telegram API 凭据、国际格式手机号和 `WEB_INITIAL_PASSWORD`。已配置 `.env` 的安装沿用现有文件，然后执行：

```bash
docker compose build
docker compose run --rm forwarder init
docker compose run --rm forwarder login
docker compose up -d
docker compose logs -f forwarder
```

`login` 在当前终端输入验证码和两步验证密码。`run --rm` 使用与正式服务相同的 `data/` 和 `temp/` 目录，容器退出后会话仍保留。`init` 重复执行保留已有设置和任务。服务启动后转发任务默认停止，在 Web 控制台手动启动。

访问 `http://127.0.0.1:10082`。Compose 固定容器内监听 `0.0.0.0:10082`，宿主机默认只开放 `127.0.0.1:10082`。远程访问可使用 SSH 隧道；需要通过服务器 IP 访问时，在 `compose.yaml` 中调整端口映射。源码服务已占用宿主机 `10082` 时，先停止它或为容器选择另一个宿主机端口。

Compose 从 `.env` 注入配置，将项目目录 `./data` 挂载到容器 `/app/data`，`./temp` 挂载到 `/app/temp`。数据库和断点位于宿主机 `data/forwarder.db`，Telegram 会话位于 `data/sessions/forwarder.session`，临时续传文件位于 `temp/`。目录不存在时，默认配置会自动创建。设置页中的临时目录使用容器路径 `/app/temp`，其子目录也会保存在宿主机 `temp/` 中。

复用源码安装的现有 `data/` 时，先停止源码服务，保留现有 `.env`，再启动容器。已有 Telegram 会话可继续使用，无需再次登录；已有数据库中的临时目录若为宿主机绝对路径，先在设置页改为 `/app/temp`，再启动转发任务。Docker 和源码服务不要同时操作同一数据库或会话。

已使用旧 Compose 命名卷的安装，需要在停服后将卷内数据导出到项目的 `data/`、`temp/`，再使用新配置。项目目录已有数据时，先核对并备份，避免覆盖；修改挂载配置不会自动迁移原卷，确认迁移完成前保留它们。

停止和更新：

```bash
docker compose down
# 更新源码后重建并启动
docker compose up -d --build
```

`down` 和 `down -v` 都保留宿主机的 `data/`、`temp/` 目录。备份数据库可使用 SQLite backup API，或在停止服务后连同整个 `data/` 目录一起备份；需要保留续传资料时也备份 `temp/`。修改 `.env` 后使用 `docker compose up -d --force-recreate` 让新配置生效；`WEB_INITIAL_PASSWORD` 仍只在首次初始化时使用。

重新登录或切换 Telegram 账号需要先停止服务：

```bash
docker compose stop forwarder
docker compose run --rm forwarder login --relogin
docker compose up -d
```

健康检查请求本机 `/api/auth`，用于确认 HTTP 服务和运行线程可用；Telegram 连接状态在控制台查看。停止容器会发送 SIGTERM，最多等待 90 秒，让 worker 正常退出并保留续传资料。

容器中的 `127.0.0.1` 指向容器自身。使用宿主机代理时，将 `TG_PROXY_URL` 的主机改为 `host.docker.internal`，并确保代理监听容器可访问的宿主机接口。启用 HTTPS 反向代理时，`WEB_TRUSTED_PROXY` 填写容器实际看到的代理 IP。

## 从源码安装与运行

按 README 从源码安装 Python 依赖并执行 `.venv/bin/python -m scripts.build_frontend` 构建前端。安装与前端构建需要 Node，构建完成后运行服务只需 Python。

默认绑定 `127.0.0.1:10082`。手动启动：

```bash
.venv/bin/tg-forward init
.venv/bin/tg-forward login
.venv/bin/tg-forward serve
```

`init` 只初始化一次，重复运行保留已有数据。`login --relogin` 用于明确切换账号，须先停止服务。Telegram 尚未登录、网络失败或 Bot 配置错误时，后台仍能查看连接状态和修改配置；启动转发返回明确的不可用状态。

源码安装可使用 `bash restart.sh`：先校验配置，再发送 SIGTERM 并等待旧转发服务退出，随后完成需要的迁移并启动新服务。旧进程未退出时脚本停止，不强制杀死。此脚本只管理本项目的转发进程。

默认数据位于 `data/`，临时文件位于 `temp/`，相对路径以项目目录为基准。自定义绝对路径可避免服务管理器工作目录变化影响数据源。`--env-file` 只选择环境文件，不改变路径基准。

## systemd 示例

以下示例假定虚拟环境与 `.env` 位于 `/opt/tg-forward`，运行用户 `tg-forward` 已拥有数据和临时目录。

```ini
[Unit]
Description=Telegram Forwarder
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tg-forward
WorkingDirectory=/opt/tg-forward
ExecStart=/opt/tg-forward/.venv/bin/tg-forward serve
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=90
UMask=0077

[Install]
WantedBy=multi-user.target
```

使用 systemd 时由 journal 收集控制台日志。不要同时用 systemd 与 `restart.sh` 管理同一个实例。所有任务在服务启动后默认停止，需要管理员启动。

## HTTPS 反向代理

本机访问或 SSH 隧道保留默认设置。Nginx 终止 HTTPS 时，在 `.env` 设置 `WEB_TRUSTED_PROXY=127.0.0.1`，并将请求代理到本机 Waitress。该设置只接受一个明确的代理 IP，默认不信任转发头。

```nginx
location / {
    proxy_pass http://127.0.0.1:10082;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_read_timeout 30s;
}
```

此处假定反向代理与 Python 位于同一主机、应用部署在域名根路径。可信代理提供 HTTPS 协议时，登录 Cookie 带 `Secure`；所有登录 Cookie 均为 HttpOnly、SameSite Strict。写请求使用 CSRF token，服务检查 Origin 与 Host。修改 `WEB_TRUSTED_PROXY` 后重启。不要添加 `*` 或信任任意客户端传来的转发头。

## 已有安装升级

1. 先构建新版本的前端资源，并准备好新依赖；停止转发任务，正常退出旧服务。
2. 保留已有 `.env`、`DB_PATH` 数据库、`SESSION_PATH` 用户会话以及尚需续传的临时目录，更新源码与 Python 依赖。可在旧服务运行时执行下面的 `--prepare`，它只准备 `.env`。
3. 仅对 SQLite 仍包含 API 凭据等部署字段的旧安装执行 `migrate-env`。已经拆分环境配置的安装跳过此步骤。
4. 执行 `verify-db` 和 `serve`。第一次加载配置自动将旧明文管理密码改成带盐哈希，清理旧配置、快照和操作记录中的密码字段，不改变当前登录密码、任务或断点。
5. 重新登录 Web，检查来源 / 目标、连接状态、实际数据和临时路径；任务默认停止，核对后手动启动。

```bash
# 仅旧配置仍包含部署字段时需要；路径按实际旧安装替换
.venv/bin/tg-forward migrate-env --db config/forwarder.db --prepare
# 正常停止旧服务后完成迁移
.venv/bin/tg-forward migrate-env
.venv/bin/tg-forward verify-db
.venv/bin/tg-forward serve
```

`migrate-env` 默认读取环境或 `.env` 中的 `DB_PATH`，尚无 `.env` 时使用 `--db` 指定旧数据库。已有配置冲突只报告变量名称，保留原文件；重复执行完成后的迁移保留现状。指定缺失或未初始化的数据库时，普通启动不会悄悄创建空数据库。

迁移保留任务、断点、去重、错误、发送意图、传输状态及 Telegram 用户会话。新认证使用 Cookie，旧 localStorage Bearer token 会被前端清除，升级后重新登录。

密码哈希迁移不能直接回退至要求明文密码的旧 Web 实现。若需回退，应使用升级前的一致数据库副本配合对应代码。使用 SQLite backup API 或停止全部写入后执行 checkpoint 来准备一致副本，不能只复制活动数据库的主文件。升级工具本身不自动创建备份或压缩归档。

## 整理旧运行文件

保留当前 `.env` 的自定义路径即可，不必移动。若要统一到默认 `data/`：

1. 停止转发及登录进程，等待正常退出。
2. 对旧数据库执行 `PRAGMA wal_checkpoint(TRUNCATE)`，确认没有繁忙连接，关闭连接后移动数据库及仍存在的 `-wal`、`-shm`、`-journal` 附属文件。更新 `DB_PATH`，核对完整性和各表数据；目标已有文件时停止。
3. 将用户会话及 `-journal`、`-wal`、`-shm`、`.lock` 附属文件一起移动到 `data/sessions`，更新 `SESSION_PATH`，避免创建另一份空会话。
4. 如系统环境同时设置这些路径，也同步修改；系统环境优先于 `.env`。
5. 旧日志 / PID 可移至 `data/logs`、`data/run`。当前 Bot 使用内存会话，不再读取旧 Bot session。

## 现场验收

本仓库自动测试使用临时数据库和模拟 Telegram。部署后检查用户手机号、来源和目标权限、论坛话题、Bot 管理员及代理，并选代表性媒体验证转发、相册、停止与续传。
