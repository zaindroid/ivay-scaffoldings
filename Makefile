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

test: ## API tests (needs Postgres: `make up` or `make local-db`); SDK tests join in M1
	cd api && ../$(VBIN)/pytest -q

# Later milestones. They fail loudly rather than pretending to pass.
e2e:
	@echo "make e2e: not implemented until M7" >&2; exit 1
size:
	@echo "make size: not implemented until M1 (SDK bundle)" >&2; exit 1
simulate:
	@echo "make simulate: not implemented until M7" >&2; exit 1
gates:
	@echo "make gates: not implemented until M8" >&2; exit 1
