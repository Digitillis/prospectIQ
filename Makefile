ROOT := $(shell pwd)

.PHONY: api dashboard dev

## Start the FastAPI backend (port 8000, auto-reload)
api:
	PYTHONPATH=$(ROOT) uvicorn backend.app.api.main:app --host 0.0.0.0 --port 8000 --reload

## Start the Next.js dashboard (port 3000)
dashboard:
	cd dashboard && npm run dev

## Run both concurrently (requires a second terminal or use tmux/screen)
dev:
	@echo "Run 'make api' and 'make dashboard' in separate terminals."
