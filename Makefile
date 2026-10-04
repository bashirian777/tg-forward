PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
NPM ?= npm

.PHONY: help install frontend dev test ui-test check build benchmark
help:
	@printf '%s\n' 'make install    Install Python development and locked Node dependencies' 'make frontend   Build and stage Vue dist for Flask' 'make dev        Start Vite (run tg-forward serve separately)' 'make test       Run Python regression tests' 'make ui-test    Build Vue and run offline Playwright checks' 'make check      Python tests, TypeScript and shell syntax checks' 'make build      Build frontend, sdist and wheel' 'make benchmark  Run simulated transfer benchmark'
install:
	$(PIP) install -e '.[dev]'
	$(NPM) --prefix frontend ci --no-audit --no-fund
frontend:
	$(PYTHON) -m scripts.build_release --skip-install --frontend-only
dev:
	$(NPM) --prefix frontend run dev
test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider
ui-test:
	$(NPM) --prefix frontend run build
	$(NPM) --prefix frontend test
check: test
	$(NPM) --prefix frontend run typecheck
	bash -n restart.sh
	git diff --check
build:
	$(PYTHON) -m scripts.build_release
benchmark:
	$(PYTHON) -m scripts.benchmark_transfer --size-mb 16 --latency-ms 20
