ROOT := $(shell pwd)

.PHONY: install api dashboard dev

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
