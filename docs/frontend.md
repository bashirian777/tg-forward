# 前端开发与测试

前端使用 Vue 3、TypeScript、Vite、Vue Router 和 Pinia，位于 `frontend/`。后端使用 Flask / Waitress，生产部署由同一端口提供 API 和构建后的静态资源。

## 开发

需要 Python 3.9 及以上、Node 22.12 及以上和 npm。先创建 `.venv`，再安装开发依赖：

```bash
python3 -m venv .venv
make install
```

按 [README](../README.md) 配置 `.env`，随后初始化数据库、登录 Telegram 并启动后端：

```bash
.venv/bin/tg-forward init
.venv/bin/tg-forward login
.venv/bin/tg-forward serve
```

另一个终端运行 `make dev`，访问 `http://127.0.0.1:5173`。Vite 将 `/api` 代理到 `127.0.0.1:10082`；后端端口变化时同步调整 `frontend/vite.config.ts`。

## 构建

```bash
make frontend
```

构建脚本使用已安装的 Node 依赖，将 `frontend/dist` 复制到 `src/tg_forwarder/web/dist`，由后端提供页面和静态资源。仅运行 `npm --prefix frontend run build` 不会更新后端的副本。生成的 dist 不提交 Git；Docker 构建会自动完成这一步。

## 自动检查

```bash
make check
npm --prefix frontend run test:browser-install
make ui-test
```

`make check` 运行 Python 回归、前端类型检查、Shell 语法和 Git 差异检查。`make ui-test` 构建前端，再依次运行模拟 API 的浏览器交互测试和连接真实 Flask / SQLite 的离线契约测试。两套浏览器测试都使用临时数据，不连接 Telegram，不读取真实 `.env` 或用户会话。

测试服务器分别监听 `18082`、`18083`，结果保存在 `frontend/test-results/ui` 和 `frontend/test-results/contract`。使用已有 Chromium 时可执行 `CHROMIUM_PATH=/path/to/chromium make ui-test`。
