VENV ?= .venv
# venv layout differs: Scripts/ on Windows, bin/ elsewhere
VBIN := $(if $(wildcard $(VENV)/Scripts),$(VENV)/Scripts,$(VENV)/bin)
PY   := $(VBIN)/python

.PHONY: install up down local-db test lint e2e size simulate gates

install: ## create the virtualenv and install the API with dev tools
	$(or $(PYTHON),python3) -m venv $(VENV)
	$$(test -d $(VENV)/Scripts && echo $(VENV)/Scripts || echo $(VENV)/bin)/python -m pip install -q -e "api[dev]"

up: ## start postgres, api and the static server (needs Docker)
	docker compose up -d --build --wait

down:
	docker compose down

local-db: ## Docker-free Postgres for tests (see NOTES.md)
	scripts/local_db.sh

lint:
	cd api && ../$(VBIN)/ruff check . && ../$(VBIN)/mypy app tests
	cd sdk && npx tsc --noEmit

test: ## API tests (needs Postgres: `make up` or `make local-db`) and SDK tests
	cd api && ../$(VBIN)/pytest -q
	cd sdk && npx vitest run

# Later milestones. They fail loudly rather than pretending to pass.
e2e:
	@echo "make e2e: not implemented until M7" >&2; exit 1
size: ## build the SDK and fail above 10,240 bytes gzipped
	cd sdk && npm run build --silent && node scripts/size.mjs
simulate:
	@echo "make simulate: not implemented until M7" >&2; exit 1
gates:
	@echo "make gates: not implemented until M8" >&2; exit 1
