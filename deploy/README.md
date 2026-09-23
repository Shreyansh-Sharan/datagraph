# Deploying datagraph

Two images, one database. The API carries its own migrations and applies them at startup, so a
release is an image tag change. The connection module (`mf-studio-connectors`) is a separate
service that this product talks to over HTTP; it is never deployed from this repository.

```
deploy/
  backend/Dockerfile        the API image (python, uvicorn)
  frontend/Dockerfile       the UI image (built SPA on nginx, which also fronts the API)
  frontend/nginx.conf.template
  compose.yml               the whole product on one machine
  compose.dev.yml           just Postgres, for running from source
  .env.example              every setting, with a comment each
  pipelines/backend.yml     Azure Pipelines: test, build, push the API image
  pipelines/frontend.yml    Azure Pipelines: type-check, test, build, push the UI image
  databricks/app.yaml       the Databricks Apps manifest
  local/                    start, stop and login-service scripts for a developer machine
```

## On one machine

```bash
cp deploy/.env.example deploy/.env      # fill it in; it holds credentials, so it is gitignored
docker compose -f deploy/compose.yml up -d --build
open http://localhost:8080
```

`migrate` runs once and the API waits for it, so two replicas never race to apply the same
migration. The UI's nginx proxies `/api` and `/mcp` to the API and `/hub` to the connection
module, which is why the browser only ever talks to one origin.

Building the UI image needs a token for the private `@polestar` feed. It travels as a BuildKit
secret and never reaches a layer:

```bash
NPM_TOKEN=... docker compose -f deploy/compose.yml build web
```

## From source

```bash
make db        # Postgres on 5439
make start     # the API and the bundled UI on 8765
cd frontend && npm run dev     # the React app on 5173, proxying to both
```

## Pipelines

Each side has its own pipeline, triggered only by its own paths, so a UI change does not rebuild
the API. Both need one Docker registry service connection (`REGISTRY_CONNECTION`); the frontend
also needs a secret variable `NPM_TOKEN` for the private feed. Neither uses a personal access
token. A pull request runs the tests and proves the image builds; only `main` pushes a tag.

| Pipeline | Triggers on | Stages |
|---|---|---|
| `backend.yml` | `backend/`, `deploy/backend/` | pytest against a real Postgres service container, then build and push |
| `frontend.yml` | `frontend/`, `deploy/frontend/` | type-check and vitest, then build and push |

## Settings

Every setting is an environment variable with the prefix `ONTOFORGE_`, listed with a comment in
[.env.example](.env.example). The ones that decide how a deployment behaves:

| Variable | What it decides |
|---|---|
| `ONTOFORGE_DATABASE_URL` | the registry database: domains, versions, triples |
| `ONTOFORGE_AUTH_MODE` | `header` trusts an identity header; `token` expects an API key |
| `ONTOFORGE_AUTH_HEADER` | which header carries the signed-in user in header mode |
| `ONTOFORGE_AUTH_DEFAULT_ROLE` | what an unknown principal may do; `viewer` in production |
| `ONTOFORGE_SOURCE_KIND` | `postgres` or `databricks`: where the mapped tables live |
| `ONTOFORGE_CONNECTIONS_HUB_URL` | the connection module; without it no source can be attached |
| `ONTOFORGE_LLM_PROVIDER` | `none` turns the assistant off and says so in the UI |

**Header mode is only safe behind a proxy that strips that header from the public.** Anything that
reaches the API directly can otherwise claim any identity. Where no such proxy exists, use token
mode and issue API keys.

## Health

| Endpoint | Answers |
|---|---|
| `GET /health` | the process is up (the container's own health check) |
| `GET /docs` | the OpenAPI console |
| `GET /mcp` | the MCP endpoint agents connect to |

## Releasing and rolling back

Images are tagged with the build number. A deployment pins a tag, so a rollback is the previous
tag redeployed. Migrations only add; no release drops a column another version still reads, which
is what makes rolling back an image safe.

## Databricks Apps

[databricks/app.yaml](databricks/app.yaml) is the manifest: `databricks apps deploy datagraph`.
The Apps proxy forwards the signed-in user as `X-Forwarded-Email`, which is the identity header
configured there. Bootstrap the first admin with `ONTOFORGE_AUTH_DEFAULT_ROLE=admin` once, assign
roles with `PUT /admin/principals/{email}`, then set the default back to `viewer`.
