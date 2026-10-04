# 部署与配置迁移

启动参数由 `.env` 或系统环境管理，运行设置和任务由 SQLite 管理。迁移工具、初始化和重启脚本都不自动创建压缩归档或历史备份。

## 已有服务升级

1. 使用当前虚拟环境安装 `requirements.txt` 中的依赖。
2. 执行 `.venv/bin/python -m src.main migrate-env --prepare`。这一步读取现有 SQLite 并准备权限为 600 的 `.env`，不修改运行数据库，不占用 Telegram 会话。
3. 检查启动参数。若已有 `.env` 与旧凭据冲突，工具会列出冲突变量名并保留原文件；先处理冲突再迁移。
4. 执行 `bash restart.sh`。脚本先校验配置，再向本项目服务发送 SIGTERM，等待任务和 worker 完成取消；旧进程未退出时中止，不强制杀死，不启动第二个实例。
5. 服务停止后，脚本完成一次性数据库配置迁移，保留任务、断点、错误、去重和当前 Web 密码。新进程使用 `serve`，默认所有任务停止。
6. 重新登录后台，检查连接状态、启动参数来源和实际临时路径，再手动启动任务。

手动切换时，先停止项目服务，再执行 `migrate-env` 和 `serve`。`bot` 保留为 `serve` 的别名。以上操作仅针对转发项目，和 PI WEB 的 session daemon 无关。

## 配置生效规则

- 系统环境变量优先于 `.env`，空值也视为明确设置；后台显示变量来源，不回显敏感值。
- API 凭据、手机号、Bot、管理员、代理、数据库／会话路径、Web 地址／端口修改后重启。
- `WEB_INITIAL_PASSWORD` 只在首次 `init` 创建运行设置时使用。以后密码与登录有效期由后台管理。
- 相对路径统一以项目目录解析。数据库路径不正确时启动报错，避免误建空配置。
- 改手机号后不会继续使用旧账号；会话手机号不匹配时停止启动任务。停止服务后执行 `login --relogin`。
- 服务未登录或 Telegram／Bot 连接失败时，Web 仍可访问并显示处理方式。

## 数据与回退边界

迁移只清理旧部署字段及其历史配置副本，不修改任务、断点、媒体文件或 Telegram 用户会话。代码可以通过 Git 回退，但迁移前版本从数据库读取 API 凭据；直接回退旧代码后需从 `.env` 恢复其所需配置。优先在新的配置模型上修复问题，避免重新引入两份权威配置。

SQLite 的 `-wal`、`-shm` 文件由数据库自行管理。运行时若人工复制数据库，应使用 SQLite backup API 获得一致副本，不能只复制活动主数据库文件。

## 整理旧运行文件

新安装的默认会话路径为 `data/sessions/forwarder.session`，`restart.sh` 的 PID 与日志分别写入 `data/run/forwarder.pid` 和 `data/logs/forwarder.log`。路径以安装目录为基准，所需目录自动创建。

已有安装的 `.env` 路径会继续生效，脚本不会擅自移动正在使用的会话。迁移旧运行文件时：

1. 先停止转发服务及使用同一会话的登录／测速进程，等待正常退出。
2. 创建 `data/sessions`、`data/run`、`data/logs`，将当前 `SESSION_PATH` 指向的用户会话和存在的 `-journal`、`-wal`、`-shm`、`.lock` 文件一起移动到会话目录；目标已有文件时停止，避免覆盖另一份登录状态。
3. 更新 `.env` 的 `SESSION_PATH=data/sessions/forwarder.session`。如系统环境变量也设置了该字段，应同步修改，因为它优先于 `.env`。
4. 将旧 `logs/bot.log` 移至 `data/logs/forwarder.log`。历史 `nohup.out` 可移至 `data/logs/nohup.out`，旧 `bot.pid` 可移至 `data/run/forwarder.pid`；重启会更新 PID。
5. 旧版留下的 `bot_session.session` 及其附属文件可移入 `data/sessions`。当前 Bot 使用内存会话，不读取或生成这份文件。
6. 执行 `bash restart.sh`，检查 Web 的 Telegram／Bot 连接状态，再手动启动任务。

这里只移动现有文件，不生成备份或归档。数据库与运行设置按现有配置使用，用户会话应保留原来的登录状态。自定义的 `SESSION_PATH` 仍然支持，不要求放在默认目录。

## 现场验收

- 首次安装、重复初始化、后台修改密码后重启、系统环境变量覆盖 `.env`。
- Telegram 实际账号一致性、Bot token、代理及目标发送权限。
- 同一代表性文件的 1／4／8 worker 吞吐量、CPU、磁盘及 FloodWait。
