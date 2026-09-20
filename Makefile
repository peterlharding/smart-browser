

HOST         := $(shell grep -s HOST=          .env | sed 's/.*=//')
APP_PORT     := $(shell grep -s APP_PORT=      .env | sed 's/.*=//')

PY           := apps/api/.venv/bin


# -----------------------------------------------------------------------------

chk-env:
	@echo "      HOST |${HOST}|"
	@echo "  APP_PORT |${APP_PORT}|"

help:  ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'


# -----------------------------------------------------------------------------

.PHONY: help check version-check version-set lint-md api-install api-dev api-test \
        api-lint api-openapi test test-api test-scripts test-ext test-pg \
        migrate migrate-status migrate-stamp


# --- the release gate -------------------------------------------------------

check: version-check lint-md api-lint test  ## Everything the release checklist requires
	@echo
	@echo "All checks passed."

version-check:  ## Fail if the version has drifted between package.json, pyproject and __init__
	@python3 scripts/version.py check

version-set:  ## Set the version everywhere: make version-set VERSION=0.2.0
	@test -n "$(VERSION)" || { echo "usage: make version-set VERSION=x.y.z"; exit 1; }
	npm version $(VERSION) --no-git-tag-version --allow-same-version >/dev/null
	@python3 scripts/version.py set $(VERSION)

lint-md:  ## Lint every markdown file we wrote
	npx --yes markdownlint-cli2 "**/*.md" "#node_modules" "#**/node_modules" "#**/.venv" "#**/venv" "#**/dist" "#**/.git"


# --- tests ------------------------------------------------------------------

test: test-api test-scripts test-ext  ## Run all tests that need no infrastructure

test-api:  ## API suite (SQLite, no infrastructure)
	cd apps/api && .venv/bin/pytest -q

test-scripts:  ## Tests for the release tooling
	apps/api/.venv/bin/pytest scripts/tests -q

test-ext:  ## Extension suite (node --test, no dependencies)
	node --test apps/extension/test/*.test.js

test-pg:  ## Run the Postgres suite (needs TEST_DATABASE_URL)
	@test -n "$(TEST_DATABASE_URL)" || \
	  { echo "TEST_DATABASE_URL is not set -- and must NOT point at the real database"; exit 1; }
	cd apps/api && TEST_DATABASE_URL="$(TEST_DATABASE_URL)" .venv/bin/pytest -m postgres -q

# --- api --------------------------------------------------------------------

api-install:  ## Create the API venv and install dependencies
	cd apps/api && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

api-dev:  ## Run the API with reload on :8000
	cd apps/api && .venv/bin/uvicorn bookmarks_api.main:app --reload --port 8000

api-lint:  ## Lint and type-check the API
	cd apps/api && .venv/bin/ruff check . && .venv/bin/mypy src

api-openapi:  ## Regenerate the committed OpenAPI contract
	cd apps/api && .venv/bin/python -c \
	  "import json, pathlib; from bookmarks_api.main import app; \
	   pathlib.Path('../../packages/shared-types/openapi.json').write_text( \
	     json.dumps(app.openapi(), indent=2) + chr(10))"
	@echo "wrote packages/shared-types/openapi.json"
	@git diff --stat packages/shared-types/openapi.json

migrate:  ## Bring the database to the revision this code requires
	cd apps/api && .venv/bin/alembic upgrade head

migrate-status:  ## Show the database's current revision against the code's head
	cd apps/api && .venv/bin/alembic current && .venv/bin/alembic heads

migrate-stamp:  ## Record a revision as applied WITHOUT running it (for a hand-applied migration)
	@test -n "$(REV)" || { echo "usage: make migrate-stamp REV=0001"; exit 1; }
	cd apps/api && .venv/bin/alembic stamp $(REV)


# -----------------------------------------------------------------------------
