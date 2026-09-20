

API_HOST     := $(shell grep -s API_HOST=      .env | sed 's/.*=//')
API_PORT     := $(shell grep -s API_PORT=      .env | sed 's/.*=//')
DB_HOST      := $(shell grep -s DB_HOST=       .env | sed 's/.*=//')
DB_PORT      := $(shell grep -s DB_PORT=       .env | sed 's/.*=//')
DB_USER      := $(shell grep -s DB_USER=       .env | sed 's/.*=//')
DB_PASSWORD  := $(shell grep -s DB_PASSWORD=   .env | sed 's/.*=//')
DB_NAME      := $(shell grep -s DB_NAME=       .env | sed 's/.*=//')

# All Python work goes through uv: it resolves the interpreter, keeps .venv in step
# with uv.lock, and syncs on demand -- so `make test` works from a clean checkout
# with no install step. `--project apps/api` lets targets run from the repo root.
UV           := uv --project apps/api


# -----------------------------------------------------------------------------

chk-env:
	@echo "  API_HOST |${API_HOST}|"
	@echo "  API_PORT |${API_PORT}|"
	@echo "   DB_HOST |${DB_HOST}|"
	@echo "   DB_PORT |${DB_PORT}|"
	@echo "   DB_USER |${DB_USER}|"
	@echo "   DB_NAME |${DB_NAME}|"

help:  ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'


# -----------------------------------------------------------------------------

venv:
	uv venv .venv

install:
	uv pip install -r requirements.txt


# -----------------------------------------------------------------------------

.PHONY: help check version-check version-set lint-md api-install api-dev api-test \
        api-lint api-openapi test test-api test-scripts test-ext test-pg \
        migrate migrate-status migrate-revision migrate-autogen migrate-stamp \
        db-connect db-doctor schema-drop


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
	cd apps/api && uv run pytest -q

test-scripts:  ## Tests for the release tooling
	$(UV) run pytest scripts/tests -q

test-ext:  ## Extension suite (node --test, no dependencies)
	node --test apps/extension/test/*.test.js

test-pg:  ## Run the Postgres suite (needs TEST_DATABASE_URL)
	@test -n "$(TEST_DATABASE_URL)" || \
	  { echo "TEST_DATABASE_URL is not set -- and must NOT point at the real database"; exit 1; }
	cd apps/api && TEST_DATABASE_URL="$(TEST_DATABASE_URL)" uv run pytest -m postgres -q

# --- api --------------------------------------------------------------------

api-install:  ## Sync the API environment from uv.lock
	$(UV) sync

api-dev:  ## Run the API with reload on :8000
	$(UV) run uvicorn bookmarks_api.main:app --reload --port 8000

api-lint:  ## Lint and type-check the API
	cd apps/api && uv run ruff check . && uv run mypy src

api-openapi:  ## Regenerate the committed OpenAPI contract
	cd apps/api && uv run python -c \
	  "import json, pathlib; from bookmarks_api.main import app; \
	   pathlib.Path('../../packages/shared-types/openapi.json').write_text( \
	     json.dumps(app.openapi(), indent=2) + chr(10))"
	@echo "wrote packages/shared-types/openapi.json"
	@git diff --stat packages/shared-types/openapi.json

# db/ has its own project: the schema belongs to the project, not to one service, so
# migrating it needs only alembic, sqlalchemy and psycopg -- not the API package.
# --autogenerate is the exception and uses the API environment (see migrate-autogen).
ALEMBIC := uv --project db run alembic -c db/alembic.ini

migrate:  ## Bring the database to the revision this code requires
	$(ALEMBIC) upgrade head

migrate-status:  ## Show the database's current revision against the code's head
	$(ALEMBIC) current && $(ALEMBIC) heads

migrate-revision:  ## New empty revision: make migrate-revision M="what it does"
	@test -n "$(M)" || { echo 'usage: make migrate-revision M="what it does"'; exit 1; }
	$(ALEMBIC) revision -m "$(M)"

migrate-autogen:  ## Revision diffed against the models; needs the API environment
	@test -n "$(M)" || { echo 'usage: make migrate-autogen M="what it does"'; exit 1; }
	$(UV) run alembic -c db/alembic.ini revision --autogenerate -m "$(M)"

migrate-stamp:  ## Record a revision as applied WITHOUT running it
	@test -n "$(REV)" || { echo "usage: make migrate-stamp REV=0001"; exit 1; }
	$(ALEMBIC) stamp $(REV)

schema-drop:  ## DESTRUCTIVE. Drop every schema object: make schema-drop CONFIRM=yes
	@test "$(CONFIRM)" = "yes" || { \
	  echo "This drops every table and type in the configured database."; \
	  echo "Re-run with CONFIRM=yes if that is what you want."; exit 1; }
	@set -a; . .env; set +a; \
	  PGPASSWORD="$$DB_PASSWORD" psql -h "$$DB_HOST" -p "$$DB_PORT" -U "$$DB_USER" \
	    -d "$$DB_NAME" -v ON_ERROR_STOP=1 \
	    -f db/schema/drop/drop_tables.sql \
	    -c 'DROP TABLE IF EXISTS alembic_version'
	@echo
	@echo "Dropped, including alembic_version -- without that, alembic would still think"
	@echo "0001 was applied and 'make migrate' would be a silent no-op. Run it now."

db-doctor:  ## Show which database the settings actually reach, and what is in it
	cd apps/api && uv run python -m bookmarks_api.doctor

db-connect:  ## psql into the database using the values in apps/api/.env
	  PGPASSWORD=${DB_PASSWORD} psql -h ${DB_HOST} -p ${DB_PORT} -U ${DB_USER} ${DB_NAME}


# -----------------------------------------------------------------------------
