# Telegram Forwarder

Telegram 图片、视频和相册转发工具，提供 Bot、Web 管理后台和 CLI。使用用户账号执行转发，Bot 用于管理。

## 安装与启动

Python 3.9 或更新版本，推荐 Python 3.12。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# 开发测试
.venv/bin/pip install -r requirements-dev.txt
```

从 https://my.telegram.org 获取 API ID／Hash，从 @BotFather 获取管理 Bot 的 token。首次初始化：

```bash
.venv/bin/python -m src.main init --api-id YOUR_API_ID --api-hash YOUR_API_HASH --phone +1234567890 --bot-token YOUR_BOT_TOKEN --admin-id YOUR_USER_ID
.venv/bin/python -m src.main login
.venv/bin/python -m src.main bot
```

Web 默认监听 `127.0.0.1:10082`。通过本机、SSH 隧道或已配置的反向代理访问。Bot 的 `/start`、`/list`、`/add`、`/status` 提供管理入口；启动、暂停、恢复、停止和删除使用按钮。

Bot 启动后任务默认停止，由管理员手动启动。CLI 的 `start` 启动所有 enabled 任务，`start <id>` 启动指定 enabled 任务。disabled 任务必须先启用；暂停保留当前传输，完成当前文件／媒体组后不再开始下一组；停止取消传输并等待 worker 退出。

```bash
.venv/bin/python -m src.main add daily --source -1001234567890 --target -1009876543210 --source-topic 456 --min-delay 10 --max-delay 20
.venv/bin/python -m src.main list
.venv/bin/python -m src.main start daily
```

任务 ID 允许 1～48 个字母、数字、下划线和短横线，兼容 Telegram 按钮的长度限制。来源和目标默认必须不同，以防止循环转发。

## 配置与存储

`config/forwarder.db` 是配置、任务、断点、传输状态、去重、错误和发送回执的权威数据源。旧 JSON 仅在空数据库首次迁移时读取；之后修改 JSON 不会更新运行配置。

首次迁移示例见 `config/config.example.json`。已有数据库通过 Web“编辑配置”修改。配置采用记录级更新和版本冲突检查；保存全局设置不会重写任务或清除断点。修改任务来源必须明确指定新起点，以及是否清空旧去重记录。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `temp_dir` | `temp` | 实际媒体工作目录，后台显示完整路径 |
| `temp_max_age_hours` | 24 | 非活动工作目录过期时间，0 禁用自动过期清理 |
| `min_free_disk_mb` | 1024 | 下载后需要保留的磁盘空间 |
| `max_concurrent_tasks` | 1 | 同时处理的媒体组上限 |
| `download_workers` | 4 | 单文件下载分块并发数，范围 1～16 |
| `upload_workers` | 4 | 单文件上传分块并发数，范围 1～16 |
| `web_auth_ttl_hours` | 24 | 从输入密码成功开始的固定登录有效期 |
| `web_port` | 10082 | 保存后重启服务才切换端口 |
| `web_password` | 空 | Web 管理密码；空时无需认证 |

登录设置可在任务运行时修改。传输目录、资源参数和端口需要先停止全部任务。保存失败不改变运行配置；其他入口已修改同一记录时提示重新读取。

登录密码支持中文。浏览器保存 token 和到期时间，不保存密码；页面轮询不延长有效期。修改有效期作用于新登录，已有 token 保留原到期时间；修改密码或服务重启撤销原 token。

数据库工具：

```bash
.venv/bin/python -m src.main verify-db
.venv/bin/python -m src.main export-json /path/to/export
.venv/bin/python -m src.main sync-json
```

`verify-db` 比较旧 JSON 与当前数据库；数据库运行后出现差异不代表数据库损坏。同步 JSON 会备份原文件。

## 转发、重试与清理

仅处理图片和视频媒体，纯文本跳过。支持随机延迟、关键词过滤、完整 hashtag 匹配／删除、来源和目标论坛话题、caption 前缀和基于 Telegram 媒体 ID 的去重。重新上传的相同内容可能有新的媒体 ID，这不是内容哈希去重。

“隐藏来源”开启时复制媒体，并在 Telegram 拒绝复制或文件引用失效时尝试下载上传。关闭时使用 Telegram 原生转发显示来源；此时不能修改 caption、删除 hashtag 或使用 send-as。发送及以频道身份发送所需权限属于登录的用户账号。

分页边界的相册会补齐，实时相册会短暂等待稳定后处理。缺少任意必需文件默认整组失败，不推进断点，也不把未发送文件计入成功或去重。穿插在相册中的其他消息必须处理完成，断点才能越过它；完成回执避免重启后重发已完成相册。

下载／上传使用 512 KiB 分块和有界 worker，默认 4 个，设为 1 可回退到顺序分块。文件中断后验证分块并补齐缺失部分，上传保留文件 ID 和完成分块。已上传媒体引用持久化，最终相册发送失败优先复用，引用失效再重新上传。网络故障退避重试；FloodWait 按 Telegram 指定时间等待；权限等错误显示 error，等待人工处理。

小磁盘机器仍建议 `max_concurrent_tasks=1`。所有下载上传的回退链路共享一个磁盘名额，同一时间仅一条链路下载并暂存文件；提速主要依靠单文件分块并发。每项上传并登记可复用引用后删除源文件，整个相册不同时占用本地空间。

工作目录按任务和传输独立管理，包含媒体、`.part`、封面、缩略图、分块清单和上传引用。成功后清理；失败／停止保留有归属的续传资料；手动“清理文件”、跳过和删除任务清理对应目录。后台全局清理跳过活动目录，启动和每 10 分钟清理过期非活动目录。

旧版根目录的封面／缩略图仅在完全符合本项目生成文件名、且对应已配置任务时登记清理。无法确认归属的历史媒体不会自动删除。迁移后通过后台确认实际临时目录；旧路径中非活动文件人工检查后再处理。

视频封面下载前刷新源引用；Pillow 把缩略图规范化为 JPEG，最长边不超过 320 像素且小于 20 KB，独立封面保留。没有可用封面时记录警告并继续，无需 ffmpeg。

发送请求保留 random_id 和成功回执，减少响应丢失带来的重复。服务端去重有实际边界，不能保证无限期 exactly-once，详见 [验证记录](docs/verification.md)。

## 验证与部署

```bash
.venv/bin/python -m pytest -q
node --check src/static/app.js
.venv/bin/python -m scripts.benchmark_transfer --size-mb 16 --latency-ms 20
```

模拟性能测试不连接 Telegram。实际速度需部署后对同一来源的代表性文件对比；不把模拟倍数当作真实提速承诺。

本次开发没有重启已有服务。上线步骤与备份／回退见 [部署说明](docs/deployment.md)，实施进度见 [TODO](TODO.md)。

主要代码：`database.py`／`config_manager.py` 保存配置；`forwarder.py` 控制顺序和断点；`message_handler.py` 过滤和媒体处理；`transfer.py` 并行传输；`reliable_sender.py` 发送身份；`workspace.py` 文件归属与清理；`web_server.py` 与 `static/` 提供后台；`main.py`／`bot.py` 提供管理入口。
