.PHONY: help start stop open test test-ui install-service uninstall-service db up down
help:             ## list the targets
	@grep -hE '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t22
start:            ## run the API on this machine, with Postgres if it is local (foreground)
	deploy/local/start.sh --open
stop:             ## stop a manually started API
	deploy/local/stop.sh
open:             ## open the app in the browser (the dev server, started by `make ui`)
	open http://127.0.0.1:5173/ui/
db:               ## just the development Postgres, in Docker
	docker compose -f deploy/compose.dev.yml up -d
test:             ## the backend suite
	.venv/bin/pytest
test-ui:          ## the frontend suite
	cd frontend && pnpm run typecheck && pnpm exec vitest run
ui:               ## the frontend dev server (install first with `make ui-install`)
	cd frontend && pnpm run dev
ui-install:       ## install the frontend packages (needs a valid Azure Artifacts token)
	cd frontend && pnpm install
up:               ## the whole product in containers (see deploy/README.md)
	docker compose -f deploy/compose.yml up -d --build
down:
	docker compose -f deploy/compose.yml down
install-service:  ## macOS: start the API at login and keep it running
	deploy/local/install-launchd.sh install
uninstall-service:
	deploy/local/install-launchd.sh uninstall
