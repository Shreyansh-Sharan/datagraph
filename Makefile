.PHONY: start stop open test install-service uninstall-service
start:            ## start Postgres, seed the demo schema, serve the API + UI (foreground)
	scripts/start.sh --open
stop:             ## stop a manually started server
	scripts/stop.sh
open:             ## open the UI in the browser
	open http://127.0.0.1:$${ONTOFORGE_PORT:-8765}/ui/
test:             ## run the test suite
	.venv/bin/pytest -q
install-service:  ## register as a macOS login service (auto-start, auto-restart)
	scripts/install-launchd.sh install
uninstall-service:
	scripts/install-launchd.sh uninstall
