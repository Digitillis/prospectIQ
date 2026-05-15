ROOT := $(shell pwd)
MIGRATIONS_DIR := $(ROOT)/supabase_migrations/migrations

.PHONY: install api dashboard dev verify-staging migrate-staging migrate-production seed-staging

## Install the backend in strict editable mode (run once after cloning/pulling).
## Strict mode registers only the 'backend' package via an import hook,
## so the local supabase/ migrations dir cannot shadow the supabase pip package.
install:
	pip install -e . --config-settings editable_mode=strict

## Start the FastAPI backend (port 8000, auto-reload).
## Requires 'make install' to have been run at least once.
api:
	uvicorn backend.app.api.main:app --host 0.0.0.0 --port 8000 --reload

## Start the Next.js dashboard (port 3000)
dashboard:
	cd dashboard && npm run dev

## Run both concurrently (requires a second terminal or use tmux/screen)
dev:
	@echo "Run 'make api' and 'make dashboard' in separate terminals."

## Verify staging environment is healthy and safe.
## Requires: STAGING_URL, STAGING_DATABASE_URL
## Example: make verify-staging STAGING_URL=https://... STAGING_DATABASE_URL=postgresql://...
verify-staging:
	@if [ -z "$(STAGING_URL)" ]; then echo "ERROR: STAGING_URL is required"; exit 1; fi
	@if [ -z "$(STAGING_DATABASE_URL)" ]; then echo "ERROR: STAGING_DATABASE_URL is required"; exit 1; fi
	@echo "--- Health check ---"
	curl -sf --max-time 10 "$(STAGING_URL)/health" && echo "OK: /health returned 200" || (echo "FAIL: health check"; exit 1)
	@echo "--- send_enabled check ---"
	@send_val=$$(psql "$(STAGING_DATABASE_URL)" -t -c \
		"SELECT send_enabled FROM outreach_send_config LIMIT 1;" | tr -d ' \n'); \
	if [ "$$send_val" != "f" ]; then \
		echo "FAIL: send_enabled=$$send_val (expected false)"; exit 1; \
	fi; \
	echo "OK: send_enabled=false"
	@echo "--- Isolation check (contacts < 1000) ---"
	@count=$$(psql "$(STAGING_DATABASE_URL)" -t -c "SELECT COUNT(*) FROM contacts;" | tr -d ' \n'); \
	if [ "$$count" -ge 1000 ]; then \
		echo "FAIL: $$count contacts (staging isolation breach)"; exit 1; \
	fi; \
	echo "OK: $$count contacts (< 1000)"

## Apply a single migration to staging.
## Requires: MIGRATION (filename only), STAGING_DATABASE_URL
## Example: make migrate-staging MIGRATION=029_outreach_send_config.sql STAGING_DATABASE_URL=postgresql://...
## See scripts/MIGRATION_ORDER.txt for the correct application order.
migrate-staging:
	@if [ -z "$(MIGRATION)" ]; then echo "ERROR: MIGRATION is required (filename only, e.g. 001_initial_schema.sql)"; exit 1; fi
	@if [ -z "$(STAGING_DATABASE_URL)" ]; then echo "ERROR: STAGING_DATABASE_URL is required"; exit 1; fi
	@if echo "$(STAGING_DATABASE_URL)" | grep -q "wlyhbdmjhgvovigogdco"; then \
		echo "FATAL: STAGING_DATABASE_URL appears to be the production database. Refusing."; exit 1; \
	fi
	@echo "Applying $(MIGRATION) to staging..."
	psql "$(STAGING_DATABASE_URL)" -f "$(MIGRATIONS_DIR)/$(MIGRATION)"
	@echo "Done: $(MIGRATION) applied to staging."

## Deploy to production via Railway CLI (requires RAILWAY_TOKEN).
## Prompts for explicit confirmation before deploying.
## Prefer the GitHub Actions workflow (deploy-production.yml) for audited deploys.
migrate-production:
	@echo ""
	@echo "WARNING: You are about to deploy to PRODUCTION."
	@echo "This action affects live data and real users."
	@echo ""
	@printf "Type 'deploy-production' to confirm: "; \
	read CONFIRM; \
	if [ "$$CONFIRM" != "deploy-production" ]; then \
		echo "Aborted."; exit 1; \
	fi
	@echo "Deploying to Railway production environment..."
	railway up --environment production --detach
	@echo "Deploy triggered. Monitor Railway dashboard for completion."

## Seed the staging database with synthetic data.
## All emails use @staging-test.invalid — non-routable by design.
## Idempotent: safe to run multiple times.
## Requires: STAGING_DATABASE_URL
## Example: make seed-staging STAGING_DATABASE_URL=postgresql://...
seed-staging:
	@if [ -z "$(STAGING_DATABASE_URL)" ]; then echo "ERROR: STAGING_DATABASE_URL is required"; exit 1; fi
	STAGING_DATABASE_URL="$(STAGING_DATABASE_URL)" SEND_ENABLED=false python scripts/seed_staging.py
