# Telegram Forwarder

Telegram群组/频道内容转发工具，支持配置转发频率、断点续传、无权限时下载转发。

## 功能

- 用户账号登录（User Client）
- **Telegram Bot管理界面**（查看/添加/暂停/删除任务）
- 配置源/目标群组或频道
- 随机延迟转发（如10s-20s）
- 断点续传，重启后继续上次进度
- 无转发权限时自动下载后重新发送
- 下载前缓存原视频缩略图和独立封面，使用 Pillow 规范化图片，无需 ffmpeg；源消息没有可用封面时记录警告并继续发送视频
- 多任务并发管理
- JSON配置存储

## 安装

```bash
pip install -r requirements.txt
```

## 使用

### 1. 初始化配置

从 https://my.telegram.org 获取 API ID 和 API Hash。
从 @BotFather 创建Bot获取 Bot Token。

```bash
python -m src.main init --api-id YOUR_API_ID --api-hash YOUR_API_HASH --phone +1234567890 --bot-token YOUR_BOT_TOKEN --admin-id YOUR_USER_ID
```

### 2. 登录用户账号

```bash
python -m src.main login
```

### 3. 启动Bot管理界面（推荐）

```bash
python -m src.main bot
```

然后在Telegram中与你的Bot对话，使用以下命令：
- `/start` - 查看帮助
- `/list` - 查看所有任务
- `/add` - 添加新任务（交互式）
- `/start_task <id>` - 启动任务
- `/pause <id>` - 暂停任务
- `/resume <id>` - 恢复任务
- `/stop <id>` - 停止任务
- `/delete <id>` - 删除任务
- `/status` - 查看运行状态

### 4. CLI方式（可选）

```bash
# 添加任务
python -m src.main add task1 --source -1001234567890 --target -1009876543210 --min-delay 10 --max-delay 20

# 查看任务
python -m src.main list

# 启动转发
python -m src.main start
```

## 配置文件

配置文件位于 `config/config.json`，参考 `config/config.example.json`。

当前运行时的权威数据源是 `config/forwarder.db`：Web 管理后台、CLI 和 Bot 的配置/任务/断点/传输状态/去重记录都会写入 SQLite。`config.json`、`progress.json`、`progress_download.json` 和旧版 `dedup_*.json` 只用于首次迁移、迁移备份和显式 `export-json` 导出；程序重启不会用旧 JSON 覆盖已经存在的数据库。首次迁移的原始文件保存在 `config/legacy-backups/`。

如果需要人工确认两边的差异，可以运行：

```bash
python -m src.main verify-db
```

### 小磁盘配置

无转发权限时，程序会下载文件再上传到目标。媒体组会逐个下载、逐个上传到 Telegram，并在 Telegram 接受每个文件后立即删除本地源文件，最后仍作为一个 album 发送。小机器建议使用本地临时目录，不要把 `temp_dir` 配置到 rclone mount：

```json
{
  "temp_dir": "/root/tools/tg-forward/temp",
  "temp_max_age_hours": 12.0,
  "max_concurrent_tasks": 1,
  "min_free_disk_mb": 1024
}
```

`max_concurrent_tasks` 限制同时处理的媒体组数量，`min_free_disk_mb` 防止开始下载后把系统盘写满。单个正在处理的视频仍需要占用本地空间，但不会同时保留整个媒体组。

视频下载前会刷新源消息并缓存原封面，封面引用过期时刷新重试，也会尝试其他静态尺寸和内嵌预览。缩略图转换为 JPEG，最长边不超过 320 像素且小于 20 KB；独立 `video_cover` 单独保留。媒体发送完成、失败或任务取消时，临时缩略图和独立封面会随媒体一起清理；启动时的过期文件清理同样覆盖这些图片。

### Web 管理密码

在 `config/config.json` 中设置 `web_password`。打开 Web 页面后先输入密码；服务端验证成功后，浏览器只在 `localStorage` 保存短期认证 token，不保存明文密码。修改密码或重启服务后，旧 token 会失效。

```json
{
  "web_password": "change-this-password"
}
```

rclone 可以继续用于其他文件或备份，但不再参与本项目的媒体临时传输链路。

## 项目结构

```
├── src/
│   ├── models.py           # 数据模型
│   ├── config_manager.py   # 配置管理
│   ├── progress_tracker.py # 进度追踪
│   ├── validators.py       # 验证函数
│   ├── utils.py            # 工具函数
│   ├── telegram_client.py  # Telegram客户端封装
│   ├── message_handler.py  # 消息处理
│   ├── forwarder.py        # 转发引擎
│   ├── task_manager.py     # 任务管理
│   ├── bot.py              # Bot管理界面
│   ├── logger.py           # 日志配置
│   └── main.py             # CLI入口
├── config/
│   └── config.example.json # 配置示例
├── tests/                  # 测试
└── temp/                   # 临时文件
```
