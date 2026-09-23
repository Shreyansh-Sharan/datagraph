.PHONY: help start stop open test test-ui install-service uninstall-service db up down
help:             ## list the targets
	@grep -hE '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t22
start:            ## run Postgres, the API and the UI on this machine (foreground)
	deploy/local/start.sh --open
stop:             ## stop a manually started API
	deploy/local/stop.sh
open:             ## open the UI in the browser
	open http://127.0.0.1:$${ONTOFORGE_PORT:-8765}/ui/
db:               ## just the development Postgres, in Docker
	docker compose -f deploy/compose.dev.yml up -d
test:             ## the backend suite
	.venv/bin/pytest
test-ui:          ## the frontend suite
	cd frontend && npx tsc --noEmit && npx vitest run
up:               ## the whole product in containers (see deploy/README.md)
	docker compose -f deploy/compose.yml up -d --build
down:
	docker compose -f deploy/compose.yml down
install-service:  ## macOS: start the API at login and keep it running
	deploy/local/install-launchd.sh install
uninstall-service:
	deploy/local/install-launchd.sh uninstall
