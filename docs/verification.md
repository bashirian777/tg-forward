# 验证记录

自动验证使用临时数据库、独立运行目录和模拟 Telegram 客户端，不连接 Telegram 或修改生产任务。浏览器回归使用真实 Chromium，并拦截全部 API。下面记录 Flask / Vue 重构后的结果。

## 当前验证

| 检查 | 结果 |
| --- | --- |
| Python 3.9.25 | 113 项 pytest 通过 |
| Python 3.12.13 | 113 项 pytest 通过 |
| TypeScript 与 Vite | 生产构建通过 |
| Playwright / Chromium | 6 项通过，包含交互及五种宽度 |
| 真实 Waitress HTTP | 同一端口的页面、登录、API、可信代理 Secure Cookie 和 CLI SIGTERM 退出通过 |
| wheel 隔离安装 | CLI、依赖、工作目录数据路径、四页 dist、缓存和 404 检查通过 |
| 旧安装升级 | 用旧提交 `aac9a15` 生成临时数据库，7 张任务 / 状态表逐行一致，密码保留，重复加载不改变记录 |
| 历史检查 | 检查 14 个可达提交，未发现环境 / 数据 / session / 归档文件路径或 API hash、Bot token、私钥的常见字面值模式 |
| Shell 与 Git 差异 | 语法和空白检查通过 |

升级检查使用合成任务、断点、穿插消息回执、发送意图、错误、去重和传输记录。已有 session 文件未被迁移流程改动；没有登录真实 Telegram。哈希迁移只预期改变密码格式 metadata、当前密码字段和历史密码副本。

Python 回归覆盖配置优先级、相对路径、初始化、旧配置迁移、会话互斥、任务状态与并发、RuntimeBridge 超时 / 退出、Cookie / CSRF / 密码撤销 / 限流，以及 Telegram / Bot 不可用时后台可用。原有可靠传输行为继续受下面的故障测试保护。

浏览器检查覆盖四页、路由直达、登录过期、筛选、任务按钮与刷新期间 pending、创建 / 编辑 / 来源确认、409 输入保留、设置、临时分区低空间、刷新失败、错误文字安全显示、Tab / Escape 焦点。1440、1024、768、390、360 像素宽度均检查四页无横向溢出，并保存明暗主题和表单截图。方法见[前端文档](frontend.md)。

这些检查不证明生产账号权限或真实网络性能，也不构成穷尽的敏感信息审计。GitHub Actions 工作流已配置；此处记录的是本地运行结果。

## 重复验证

```bash
make install
make frontend
make check
npm --prefix frontend run test:browser-install
make ui-test
make build
.venv/bin/python -m scripts.check_release dist/telegram_forwarder-0.2.0-py3-none-any.whl
```

`check_release` 在临时虚拟环境安装 wheel，不依赖源码或 Node，检查 CLI、依赖与静态资源。Python 测试的真实 HTTP 用临时端口启动离线运行时，不使用现有服务端口。

## 已验证的故障行为

- 下载中断后补缺失块；已记录块逐块校验 SHA-256，损坏块重新下载。
- 文件预分配大小不能代替分块完整性；成功文件仍检查块和总大小。
- 文件引用过期刷新同一源媒体；源文件删除或替换时需要人工处理。
- 上传中断保留文件 ID 和完成分块，继续上传缺失部分；完整文件重新进入下载不改变上传续传身份。
- 取消等待所有 worker 退出，避免清理后仍写文件。
- 请求响应丢失后复用持久化 `random_id`；本地发送回执避免再次发送。
- 已上传媒体引用保存在任务目录，最终发送失败可复用，引用过期后重新传输。
- 相册边界补齐，穿插消息不被断点跳过；明确跳过只处理当前媒体组。
- 失败与取消保留有归属文件，清理排除活动传输和无归属文件。

## 模拟分块延迟对比

```bash
make benchmark
```

此前的 16 MiB 文件、每个请求固定等待 20 ms、512 KiB 分块记录如下；输出文件逐字节检查通过：

| worker 数 | 下载时间（秒） | 上传时间（秒） |
| --- | --- | --- |
| 1 | 0.702 | 0.657 |
| 4 | 0.193 | 0.169 |
| 8 | 0.106 | 0.120 |

结果验证请求能重叠等待，只反映模拟条件。实际性能受网络、数据中心、磁盘、CPU、账号及限流影响，不能用作真实提速承诺。默认 worker 为 4，可降至 1；小文件不超过分块数。

## 部署后的真实对比

停止项目服务并释放用户会话后，对同一来源的代表性文档 / 视频运行：

```bash
.venv/bin/python -m scripts.benchmark_live --task-id YOUR_TASK --message-id SOURCE_MESSAGE_ID --output /path/to/new-report.json
```

脚本与服务共用会话锁，从 `.env` 读取 API 凭据及 session，从 SQLite 读取来源任务并核对手机号。依次比较 Telethon 标准传输及 1 / 4 / 8 worker，默认最大文件 256 MiB，单次超时 180 秒。下载与标准下载的 SHA-256 比较；上传只保存 Telegram 临时分块，不发送目标消息。任一失败立即停止。

结果包含耗时、速度、CPU、RSS 和失败类型，重复至少三轮并观察磁盘、FloodWait 和网络。该脚本不测试最终相册发送、封面和目标权限，需在选定任务上另行验收。真实测试尚未执行，worker 默认值没有依据真实网络调优。

Telegram `random_id` 不保证无限期跨重试 exactly-once。媒体变更、引用失效、人工调整断点及服务端去重记录失效仍需检查。
