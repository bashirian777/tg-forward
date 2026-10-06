# 前端开发与测试

前端使用 Vue 3、TypeScript、Vite、Vue Router 和 Pinia，位于 `frontend/`。后端使用 Flask / Waitress，生产部署由同一端口提供 API 和构建后的静态资源。

## 开发

需要 uv、Node 22.12 及以上和 npm。创建并激活 Python 环境，再安装开发依赖：

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r pyproject.toml --extra dev
npm --prefix frontend ci --no-audit --no-fund
```

按 [README](../README.md) 配置 `.env`，随后初始化数据库、登录 Telegram 并启动后端：

```bash
python main.py init
python main.py login
python main.py serve
```

另一个终端在项目根目录运行 `npm --prefix frontend run dev`，访问 `http://127.0.0.1:5173`。Vite 将 `/api` 代理到 `127.0.0.1:10082`；后端端口变化时同步调整 `frontend/vite.config.ts`。

## 构建

```bash
python -m scripts.build_frontend --skip-install
```

构建脚本使用已安装的 Node 依赖，将 `frontend/dist` 复制到 `src/tg_forwarder/web/dist`，由后端提供页面和静态资源。仅运行 `npm --prefix frontend run build` 不会更新后端的副本。生成的 dist 不提交 Git；Docker 构建会自动完成这一步。

## 自动检查

在项目根目录、已激活的虚拟环境中执行：

```bash
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
npm --prefix frontend run typecheck
bash -n run.sh
git diff --check
```

这些命令依次运行 Python 回归、前端类型检查、Shell 语法和 Git 差异检查。`PYTHONPATH` 让测试及其启动的子进程能直接导入源码。

在同一终端中安装浏览器、构建前端并运行浏览器测试：

```bash
npm --prefix frontend run test:browser-install
npm --prefix frontend run build
npm --prefix frontend test
```

浏览器测试依次运行模拟 API 的交互测试和连接真实 Flask / SQLite 的离线契约测试。两套测试都使用临时数据，不连接 Telegram，不读取真实 `.env` 或用户会话。

测试服务器分别监听 `18082`、`18083`，结果保存在 `frontend/test-results/ui` 和 `frontend/test-results/contract`。使用已有 Chromium 时可跳过浏览器安装，执行 `CHROMIUM_PATH=/path/to/chromium npm --prefix frontend test`。
