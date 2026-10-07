VENV ?= .venv
# The stack's published ports (see docker-compose.yml). Override API_PORT if 8000 is taken.
API_PORT ?= 8000
STATIC_PORT ?= 8080
DEV_DB ?= postgresql+asyncpg://ivay:ivay_dev@127.0.0.1:5432/ivay
# venv layout differs: Scripts/ on Windows, bin/ elsewhere
VBIN := $(if $(wildcard $(VENV)/Scripts),$(VENV)/Scripts,$(VENV)/bin)
PY   := $(VBIN)/python

.PHONY: install up down local-db test lint audit-dry e2e size simulate gates live

install: ## create the virtualenv and install the API with dev tools
	$(or $(PYTHON),python3) -m venv $(VENV)
	$$(test -d $(VENV)/Scripts && echo $(VENV)/Scripts || echo $(VENV)/bin)/python -m pip install -q -e "api[dev]" -e "analysis[dev]"

up: ## start postgres, api and the static server (needs Docker)
	docker compose up -d --build --wait

down:
	docker compose down

local-db: ## Docker-free Postgres for tests (see NOTES.md)
	scripts/local_db.sh

lint:
	cd api && ../$(VBIN)/ruff check . ../scripts && ../$(VBIN)/mypy app tests
	cd analysis && ../$(VBIN)/ruff check . && ../$(VBIN)/mypy ivay_analysis tests
	cd sdk && npx tsc --noEmit
	cd e2e && npx tsc --noEmit

test: ## API, analysis (needs Postgres: `make up` or `make local-db`) and SDK tests
	cd api && ../$(VBIN)/pytest -q
	cd analysis && ../$(VBIN)/pytest -q
	cd sdk && npx vitest run

audit-dry: ## merchant data audit on sample data (no network, no credentials)
	$(PY) scripts/audit_merchant_data.py --dry

e2e: ## Playwright against the running stack (start it first: docker compose up -d --build --wait)
	@curl -fsS http://localhost:$(API_PORT)/health >/dev/null || { echo "make e2e: the API is not answering on :$(API_PORT). Start the stack first: API_PORT=$(API_PORT) docker compose up -d --build --wait" >&2; exit 1; }
	@curl -fsS http://localhost:$(STATIC_PORT)/products/tee.html >/dev/null || { echo "make e2e: the static server is not answering on :$(STATIC_PORT)" >&2; exit 1; }
	cd sdk && npm run build --silent
	DATABASE_URL=$(DEV_DB) API_PORT=$(API_PORT) STATIC_PORT=$(STATIC_PORT) $(PY) scripts/seed_dev.py
	cd e2e && API_PORT=$(API_PORT) npx playwright test
size: ## build the SDK and fail above 10,240 bytes gzipped
	cd sdk && npm run build --silent && node scripts/size.mjs
simulate: ## write SIMULATED sessions with planted truth to the dev database (shop sim_shop)
	DATABASE_URL=$(DEV_DB) $(PY) scripts/simulate_sessions.py --truncate
SHOP ?= sim_shop
gates: ## the gate report for a shop (default: the simulated shop; SHOP=my_shop for real data)
	cd sdk && npm run build --silent
	DATABASE_URL=$(DEV_DB) $(PY) -m ivay_analysis.report --shop $(SHOP)
LIVE_SHOP ?= shop_dev
live: ## follow incoming events in real time (LIVE_SHOP=shop_dev by default)
	DATABASE_URL=$(DEV_DB) $(PY) -u scripts/live_view.py --shop $(LIVE_SHOP)
