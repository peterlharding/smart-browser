

# `?=`, not `:=`: a value already in the environment wins over .env. With `:=` the .env
# value replaced it, and because make exports a variable that arrived from the
# environment, it replaced it in the recipe too -- so `DB_NAME=page_history_test make
# migrate` announced the test database and migrated the real one.
API_HOST     ?= $(shell grep -s API_HOST=      .env | sed 's/.*=//')
API_PORT     ?= $(shell grep -s API_PORT=      .env | sed 's/.*=//')
DB_HOST      ?= $(shell grep -s DB_HOST=       .env | sed 's/.*=//')
DB_PORT      ?= $(shell grep -s DB_PORT=       .env | sed 's/.*=//')
DB_USER      ?= $(shell grep -s DB_USER=       .env | sed 's/.*=//')
# DB_PASSWORD is deliberately NOT a make variable. Make echoes recipes with variables
# already substituted, so a single un-@'d line puts the password in the terminal, the
# scrollback, and any CI log. The recipes below read it in the shell instead, where make
# never sees it.
DB_NAME      ?= $(shell grep -s DB_NAME=       .env | sed 's/.*=//')
# The role that installs extensions. Not DB_USER: pgvector is not a trusted extension, so
# CREATE EXTENSION needs a superuser, and the application role is deliberately not one.
# Override on the command line if your superuser is named something else:
#     make db-bootstrap PG_SUPERUSER=admin
PG_SUPERUSER ?= postgres

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

.PHONY: help check version-check version-set lint-md api-install api-dev api-test \
        api-lint api-openapi openapi-check test test-api test-scripts test-ext test-pg \
        migrate migrate-status migrate-revision migrate-autogen migrate-stamp \
        db-connect db-doctor db-bootstrap schema-drop rehash-urls \
        worker embed crawl-backfill crawl-status test-model \
        browser-install browser-build browser-dev browser-package browser-package-check browser-release browser-check test-browser-e2e test-browser-e2e-packaged


# --- the release gate -------------------------------------------------------

check: version-check openapi-check lint-md api-lint test browser-check  ## Everything the release checklist requires
	@echo
	@echo "All checks passed."

# uv.lock records the API package's own version, so a bump leaves it stale, and the next
# `uv run` rewrites it after the release commit. `lock --check` fails on that; UV_FROZEN
# is unset for it because under UV_FROZEN it only checks the file parses (CI sets it).
version-check:  ## Fail if the version has drifted, or a lockfile has fallen behind its pyproject
	@python3 scripts/version.py check
	@env -u UV_FROZEN $(UV) lock --check --quiet || { \
	  echo "apps/api/uv.lock is stale: run 'uv --project apps/api lock' and commit it"; exit 1; }
	@env -u UV_FROZEN uv --project db lock --check --quiet || { \
	  echo "db/uv.lock is stale: run 'uv --project db lock' and commit it"; exit 1; }

version-set:  ## Set the version everywhere: make version-set VERSION=0.2.0
	@test -n "$(VERSION)" || { echo "usage: make version-set VERSION=x.y.z"; exit 1; }
	npm version $(VERSION) --no-git-tag-version --allow-same-version >/dev/null
	@python3 scripts/version.py set $(VERSION)
	$(UV) lock --quiet
	@$(MAKE) --no-print-directory api-openapi

lint-md:  ## Lint every markdown file we wrote
	npx --yes markdownlint-cli2 "**/*.md" "#node_modules" "#**/node_modules" "#**/.venv" "#**/venv" "#**/dist" "#**/.git" "#**/test-results"


# --- tests ------------------------------------------------------------------

test: test-api test-scripts test-ext  ## Run all tests that need no infrastructure

test-api:  ## API suite (SQLite, no infrastructure)
	cd apps/api && uv run pytest -q

test-scripts:  ## Tests for the release tooling
	$(UV) run pytest scripts/tests -q

test-model:  ## The real embedding model: downloads it once (64 MB) into EMBEDDING_CACHE_DIR
	cd apps/api && uv run pytest -m model -q

test-ext:  ## Extension suite (node --test, no dependencies)
	node --test apps/extension/test/*.test.js

# .env is optional here: CI has none and passes TEST_DATABASE_URL instead. DB_NAME falls
# back to the same default as config.py, so the refusal below still names the database a
# default configuration would reach rather than matching nothing.
test-pg:  ## Postgres suite against <DB_NAME>_test (creates and drops tables there)
	@set -a; if [ -f ./.env ]; then . ./.env; fi; set +a; \
	  DB_NAME="$${DB_NAME:-page_history}"; \
	  url="$(TEST_DATABASE_URL)"; \
	  if [ -z "$$url" ]; then \
	    url="postgresql+psycopg://$$DB_USER:$$DB_PASSWORD@$$DB_HOST:$$DB_PORT/$${DB_NAME}_test"; \
	  fi; \
	  case "$$url" in \
	    */$$DB_NAME|*/$$DB_NAME\?*) \
	      echo "REFUSING: that URL points at $$DB_NAME, your real database."; \
	      echo "This suite creates and drops tables. Use a scratch one."; \
	      exit 1;; \
	  esac; \
	  target="$${url##*/}"; echo "running against $${target%%\?*}"; \
	  cd apps/api && TEST_DATABASE_URL="$$url" uv run pytest -m postgres -q

# --- the browser (ADR 0015) -------------------------------------------------

browser-install:  ## Install the browser's dependencies from package-lock.json
	npm ci

browser-build:  ## Build the browser into apps/browser/out
	npm --workspace apps/browser run build

browser-dev:  ## Build and run the browser
	npm --workspace apps/browser run dev

browser-package: browser-build  ## Package Smart-Browser.app, signed ad hoc, into apps/browser/dist (ADR 0018)
	cd apps/browser && node package.mjs

browser-package-check: browser-package  ## Package, then prove the package starts, serves its UI and quits
	cd apps/browser && SMART_BROWSER_APP="$$PWD/dist/Smart-Browser-darwin-arm64/Smart-Browser.app" \
	  npx playwright test -c playwright.packaged.config.ts

browser-release: browser-build  ## Package, sign with Developer ID, notarize: the DMG and zip a release carries
	cd apps/browser && node package.mjs --release

browser-check:  ## Type-check the browser and run its unit tests
	npm --workspace apps/browser run typecheck
	npm --workspace apps/browser test

# The built app against the real API on <DB_NAME>_test and a local site. Refuses the real
# database, as test-pg does: global setup drops and rebuilds the test database's tables.
test-browser-e2e: browser-build  ## End-to-end: the browser against the API on <DB_NAME>_test
	@set -a; if [ -f ./.env ]; then . ./.env; fi; set +a; \
	  DB_NAME="$${DB_NAME:-page_history}"; \
	  url="$(TEST_DATABASE_URL)"; \
	  if [ -z "$$url" ]; then \
	    url="postgresql+psycopg://$$DB_USER:$$DB_PASSWORD@$$DB_HOST:$$DB_PORT/$${DB_NAME}_test"; \
	  fi; \
	  case "$$url" in \
	    */$$DB_NAME|*/$$DB_NAME\?*) \
	      echo "REFUSING: that URL points at $$DB_NAME, your real database."; exit 1;; \
	  esac; \
	  cd apps/browser && TEST_DATABASE_URL="$$url" npx playwright test

test-browser-e2e-packaged: browser-package  ## End-to-end, against the packaged Smart-Browser.app (ADR 0018)
	@set -a; if [ -f ./.env ]; then . ./.env; fi; set +a; \
	  DB_NAME="$${DB_NAME:-page_history}"; \
	  url="$(TEST_DATABASE_URL)"; \
	  if [ -z "$$url" ]; then \
	    url="postgresql+psycopg://$$DB_USER:$$DB_PASSWORD@$$DB_HOST:$$DB_PORT/$${DB_NAME}_test"; \
	  fi; \
	  case "$$url" in \
	    */$$DB_NAME|*/$$DB_NAME\?*) \
	      echo "REFUSING: that URL points at $$DB_NAME, your real database."; exit 1;; \
	  esac; \
	  cd apps/browser && SMART_BROWSER_APP="$$PWD/dist/Smart-Browser-darwin-arm64/Smart-Browser.app" TEST_DATABASE_URL="$$url" npx playwright test

# --- api --------------------------------------------------------------------

api-install:  ## Sync the API environment from uv.lock
	$(UV) sync

# Where it listens comes from API_HOST and API_PORT, read from .env above (or the
# environment), so the address a client is configured with is written down once.
api-dev:  ## Run the API with reload on API_HOST:API_PORT from .env (default 127.0.0.1:8000)
	$(UV) run uvicorn bookmarks_api.main:app --reload \
	  --host $(or $(API_HOST),127.0.0.1) --port $(or $(API_PORT),8000)

api-lint:  ## Lint and type-check the API
	cd apps/api && uv run ruff check . && uv run mypy src

# The contract as the app describes it now. It embeds the release version, so a bump makes
# the committed file stale: 0.2.0 was tagged with a contract that said 0.1.0 because only
# CI compared them. version-set now regenerates it, and `make check` compares it.
OPENAPI      := packages/shared-types/openapi.json
OPENAPI_DUMP := cd apps/api && uv run python -c "import json, sys; \
	from bookmarks_api.main import app; \
	sys.stdout.write(json.dumps(app.openapi(), indent=2) + chr(10))"

# The browser's types are generated from the contract, so a contract change that breaks
# the browser fails its type check (ADR 0015). Regenerated with the contract, checked with it.
API_TYPES    := apps/browser/src/shared/api-types.ts
TYPES_FROM    = npx --no-install --loglevel=warn openapi-typescript $(1) -o $(2) >/dev/null

api-openapi:  ## Regenerate the committed OpenAPI contract, and the browser's types from it
	@$(OPENAPI_DUMP) > $(CURDIR)/$(OPENAPI)
	@$(call TYPES_FROM,$(OPENAPI),$(API_TYPES))
	@echo "wrote $(OPENAPI) and $(API_TYPES)"
	@git diff --stat $(OPENAPI) $(API_TYPES)

openapi-check:  ## Fail if the contract, or the browser's types from it, differ from what the app serves
	@$(OPENAPI_DUMP) | diff -q - $(CURDIR)/$(OPENAPI) >/dev/null || { \
	  echo "$(OPENAPI) is stale: run 'make api-openapi' and commit it"; exit 1; }
	@tmp=$$(mktemp -d); $(call TYPES_FROM,$(OPENAPI),$$tmp/api-types.ts) && \
	  diff -q $$tmp/api-types.ts $(API_TYPES) >/dev/null || { \
	  rm -rf $$tmp; echo "$(API_TYPES) is stale: run 'make api-openapi' and commit it"; exit 1; }; \
	  rm -rf $$tmp

# --- the crawl worker (ADR 0012) --------------------------------------------

worker:  ## Run the crawl worker until stopped: [ONCE=yes] to drain what is due and exit
	cd apps/api && uv run python -m bookmarks_api.worker $(if $(filter yes,$(ONCE)),--once)

embed:  ## Run the embedding pass until stopped: [ONCE=yes] to embed what is waiting and exit
	cd apps/api && uv run python -m bookmarks_api.embedder $(if $(filter yes,$(ONCE)),--once)

crawl-backfill:  ## Queue every bookmark that has never been fetched
	cd apps/api && uv run python -m bookmarks_api.worker backfill

crawl-status:  ## Crawl jobs by state, and the latest errors
	cd apps/api && uv run python -m bookmarks_api.worker status

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
	@# Every revision's drop script, newest first: 0002's tables hold foreign keys to
	@# 0001's, so dropping 0001's alone fails part way through.
	@# .env is read for DB_PASSWORD only. The connection uses make's values, which let the
	@# environment win; re-reading them from .env here would drop the .env database while
	@# `DB_NAME=scratch make schema-drop` asked for another.
	@set -a; . ./.env; set +a; \
	  echo "Dropping every schema object in $(DB_NAME) on $(DB_HOST):$(DB_PORT)"; \
	  PGPASSWORD="$$DB_PASSWORD" psql -h "$(DB_HOST)" -p "$(DB_PORT)" -U "$(DB_USER)" \
	    -d "$(DB_NAME)" -v ON_ERROR_STOP=1 \
	    -f db/schema/drop/drop_saved_title.sql \
	    -f db/schema/drop/drop_content.sql \
	    -f db/schema/drop/drop_tables.sql \
	    -c 'DROP TABLE IF EXISTS alembic_version'
	@echo
	@echo "Dropped, including alembic_version -- without that, alembic would still think"
	@echo "0001 was applied and 'make migrate' would be a silent no-op. Run it now."

# Once per database, and the test database counts: `make db-bootstrap DB=page_history_test`.
# Revision 0002 names the exact command, database included, when the extension is missing.
DB ?= $(DB_NAME)

db-bootstrap:  ## Install the pgvector extension (superuser, once per database): [DB=name]
	@echo "Running db/schema/bootstrap.sql in $(DB) as the superuser role."
	@echo "pgvector is not a trusted extension, so the application role cannot do this."
	psql "postgresql://$(PG_SUPERUSER)@$(DB_HOST):$(DB_PORT)/$(DB)" \
	  -v ON_ERROR_STOP=1 -f db/schema/bootstrap.sql

# After any change to urlnorm.py -- including a new tracking parameter -- existing rows hold
# keys the new rules would not produce, and a re-save of the same page misses its row.
# Without CONFIRM=yes this only reports. Collisions and invalid rows are never touched.
rehash-urls:  ## Rekey bookmarks under the current URL rules: [CONFIRM=yes] to apply
	cd apps/api && uv run python -m bookmarks_api.rehash $(if $(filter yes,$(CONFIRM)),--confirm)

db-doctor:  ## Show which database the settings actually reach, and what is in it
	cd apps/api && uv run python -m bookmarks_api.doctor

db-connect:  ## psql into the database using the values in .env
	@set -a; . ./.env; set +a; \
	  PGPASSWORD="$$DB_PASSWORD" psql -h ${DB_HOST} -p ${DB_PORT} -U ${DB_USER} ${DB_NAME}


# -----------------------------------------------------------------------------
