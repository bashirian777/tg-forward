# 贡献指南

欢迎问题报告和小范围改进。当前许可证待维护者确定，选择前不应将仓库视为已授予开源许可。无需真实 Telegram 账号即可运行自动测试。

## 环境与命令

支持 Linux，Python 3.9 及以上，推荐 3.12；前端构建需要 Node 22.12 及以上和 npm。

```bash
python3 -m venv .venv
make install
make frontend
make test
npm --prefix frontend run test:browser-install
make ui-test
```

`make install` 安装 Python 开发依赖和锁定的 Node 依赖。`make dev` 启动 Vite，后端另用 `tg-forward serve`。常用命令可执行 `make help` 查看。不要提交 `.env`、数据库、session、媒体、归档、node_modules 或生成的 dist。

## 目录与状态归属

```text
src/tg_forwarder/
├── cli.py / __main__.py     # tg-forward 和 python -m tg_forwarder
├── config/                 # 启动环境、运行模型、路径、校验、旧配置迁移
├── tasks/                  # 任务模型、校验、错误、统一管理入口
├── forwarding/             # 相册调度、过滤、复制与下载回退
├── telegram/               # Telethon、会话锁、分块传输、发送回执、封面
├── storage/                # SQLite、配置、断点、去重、任务工作目录
├── runtime/                # 生命周期、RuntimeBridge、管理操作、HTTP 启动
├── web/                    # Flask factory、Blueprints、认证、构建后的 dist
└── bot/                    # 管理命令、任务创建会话
frontend/                   # Vue / TypeScript
scripts/                    # 构建与测速
└── tests/                  # Python 和 HTTP 回归
```

长生命周期 asyncio 循环是业务状态的唯一所有者。Flask HTTP 线程通过 `RuntimeBridge` 调用管理操作，不直接访问任务内部字典、Telethon 或进度缓存。查询返回独立快照；超时或浏览器断开不取消已提交业务，使用 operation ID 查询结果。

新增任务操作放在 `TaskManager`，Web、Bot、CLI 复用其公开方法。复合操作持有一个任务锁，锁内调用私有步骤，避免重复获取同一锁。设置变更和启动通过设置锁协调。保持 SQLite 为唯一运行配置来源，不恢复 JSON 配置同步。

涉及相册边界、取消、下载块校验、上传身份、`random_id` 或发送回执时，保留既有可靠性测试，增加针对具体故障的回归。普通样式 / 文案变更用构建和现有浏览器测试验证，避免增加只重复实现细节的测试。

## 提交变更

保持 PR 聚焦。说明触发条件、变更后的行为、验证命令及兼容影响。附必要截图或复现步骤，隐藏真实账号、路径凭据和 Telegram 内容。提交前运行 `make check`，前端交互变化另运行 `make ui-test`。真实 Telegram 测速需由维护者明确安排，自动检查不连接 Telegram。

## 发布构建

```bash
make build
```

`python -m scripts.build_release` 执行 `npm ci`、TypeScript 检查、Vite 构建，复制 dist 至包内并使用 Python build 生成 `dist/*.whl` 和 `dist/*.tar.gz`。sdist 包含前端源码 / lockfile、脚本和文档，wheel 包含 Python 包与 dist。

发布前核对版本、许可证、文档和 Git 状态，确认 wheel 包含 `web/dist/index.html` 与哈希资源，排除运行数据和凭据。CI 在临时环境检查 wheel 安装、CLI、Flask 静态路由；在目标机器还需按部署说明核对真实 Telegram 权限和续传。当前工作不会自动推送、发布包或重启生产服务。
