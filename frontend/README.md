# datagraph UI (microfrontend)

React + TypeScript + Vite front end for datagraph, built from the `Datagraph UI.html` design in this
folder and the blueprint in `docs/UI-BLUEPRINT.html`. It talks to the backend only through the
`DatagraphApi` port (`src/api/types.ts`), so it runs against design data today and the REST API
during integration without touching the screens.

## Run

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173/ui/  (mock data, Databricks adapter)
```

Environment (`.env.local`, see `.env.example`):

| Variable | Values | Effect |
|---|---|---|
| `VITE_API_MODE` | `mock` (default) / `rest` | `mock` uses the in-memory adapter with the design's rgm / hr / finops domains; `rest` calls the backend through the dev proxy (`/api` → `VITE_API_TARGET`, default `http://127.0.0.1:8765`). |
| `VITE_SOURCE_KIND` | `databricks` (default) / `postgres` | Mock only. Switches the source chip, catalog naming (`rgm.gold.dim_customer` vs `rgm_gold.dim_customer`), inferred-key badges and the SQL dialect of the mapping designer. In `rest` mode the kind comes from `GET /auth/config`. |
| `VITE_ROLE` | `viewer` / `builder` / `reviewer` / `admin` | Mock identity; the top-bar switch changes it at runtime. |
| `VITE_CATALOG_DENIED` | `true` | Mock: makes the Databricks catalog fail with `INSUFFICIENT_PERMISSIONS` so the permission-error paths (Metadata, Settings → Test connection) can be exercised. |
| `VITE_CONNECTIONS_URL` | `/hub` (dev) / gateway route (prod) | Where the **connection module** (`mf-studio-connectors` hub) is reached from the browser. Empty: the Configure screen shows the domain's connection pickers only and says the module is not configured. |
| `VITE_HUB_TARGET` | `http://127.0.0.1:8025` | Dev only: what the `/hub` proxy forwards to. |

## The connection module

Connections (warehouses and AI providers) are **not** implemented here. They belong to the
Polestar connection module, a separate microservice (`mf-studio-connectors`: hub API + connector
plugins). This front end consumes it as a package:

- `@polestar/connections` (from the `microservices-shared` feed, see `.npmrc`) renders the
  connection form from each connector's JSON Schema, runs tests through the hub and shows the
  step-by-step report. `ConnectionsProvider` is mounted in `App.tsx`; the Configure screen's
  connection manager is built from `ConnectionForm`, `TestReportView`, `useConnections`,
  `useConnectionTypes` and `useTestConnection`.
- The datagraph API only *reads* the hub (connector types, masked configs, a test of a saved
  connection) to render the Home cards and a domain's source facts, and stores hub connection
  ids on domains. Credentials never pass through datagraph.

Locally: run the hub (`uvicorn hub.main:app --port 8025` in the connectors repo), set
`ONTOFORGE_CONNECTIONS_HUB_URL=http://127.0.0.1:8025` for the datagraph API and
`VITE_CONNECTIONS_URL=/hub` for this front end.

**Reading through a domain's connection.** Browsing, previews, snapshots, drafts and builds open
the domain's primary connection themselves: the API fetches its credentials from the hub with a
service token (`GET /connections/{id}/credentials`, audited by the hub, never exposed to browsers
or agents). Generate one token, put it in the hub's `CM_SERVICE_TOKENS` and in the API's
`ONTOFORGE_CONNECTIONS_HUB_SERVICE_TOKEN`. Without it, only the deployment's own source
(`ONTOFORGE_SOURCE_KIND` + `DATABRICKS_*`) is available, and a domain that names a connection
gets a clear error saying so. Databricks connections need a personal access token; Postgres
connections work as they are.

```bash
npm test               # vitest: adapter naming/SQL dialects, lifecycle, builds, triples, Ask, shell rendering
npm run build          # tsc + vite build → dist/ (served under /ui/)
npm run preview        # serves dist at http://localhost:4174/ui/
```

## Layout

```
src/
  api/        types.ts (the port + shared model), mock.ts (design data, live builds), rest.ts (backend mapping, falls back to mock per method), index.ts (adapter selection)
  state/      app.tsx (config, identity, toast, useLoad), domain.tsx (domain/version context, useGo/useParam navigation)
  layout/     Shell.tsx (top bar with pipeline crumbs + source chip, side nav with version picker)
  components/ ui.tsx (buttons, cards, pills, tabs, dialog, toast, skeletons), icons.tsx, Stage.tsx (node-link map on React Flow + dagre), lifecycle.tsx (version actions)
  screens/    Home (Ask + domain cards), Overview, Versions, Metadata, Ontology, Mapping, Rules, Quality, Build, Explore, Triples, Analytics, Settings, Tasks, Admin
  theme.css   design tokens and primitives
```

Routes (hash): `#/`, `#/tasks`, `#/admin`, `#/d/:domain[/screen]?v=3&cls=Sale&panel=data&table=fct_sales&tab=dq&entity=C-10482&q=…`.
Sub-state lives in the query string so every screen deep-links.

## Integration plan

`RestApi extends MockApi`: each method with a settled backend contract is overridden to call the API;
everything else still returns design data. Replace the fallbacks method by method; the screens do not
change. Backend shapes are documented in `docs/UI-BLUEPRINT.html` §8.

Wired to the API today: config, me, domains and cards, the **version mechanism** (see below), comments,
audit, catalog, ontology, mapping status, table preview, per-class SQL, builds with polling, search,
entity, graph status, triples, connections (read-only, via the hub), domain settings, tasks, bundle export.

### Sources and schemas

A domain reads from **several sources**. Each source is one connection from the connection module
(or the deployment's env source) with its own catalog and an ordered list of schemas; the first
source is the primary one, whose first schema is where the catalog browser opens and short table
names resolve. A connection identifies the server and the credentials, never a schema, so one
connection can carry many schemas and several domains can share it.

Every domain also needs **one AI connection** once the connection module is configured: the New
domain dialog asks for it and the Configure screen refuses to save without it.

The Configure screen's Source card edits the list (`sources` on `PUT /domains/{name}`); the older
single-source keys (`connection_id`, `default_catalog`, `schemas`, `default_schema`) still work and
act on the primary source. Picking a connection fixes the catalog (the one stored on the connection
in the module) and the schema picker is filled from the module's browse API with that connection's
own credentials (`client.browse(id)` from `@polestar/connections`, cached per connection for the
session). When the module is not configured or cannot browse, a typed schema name is accepted and
`GET /catalog/schemas` (the deployment's source) suggests names. Leaving a source's schemas empty
means every schema it offers. The Metadata picker lists every source's schemas, labelled
`connection · catalog.schema`.

### The scan (metadata snapshot)

The Metadata screen browses the source's tables per schema and imports the ticked ones into the
draft's snapshot (`POST /versions/{id}/metadata/import` with `schema_name` and `tables`): columns,
types, keys and comments are captured, and the list marks what the snapshot holds
(`GET /versions/{id}/metadata`). "Refresh snapshot" re-reads the source and reports added, removed
or retyped columns. Both need a draft whose lease you hold, like every other edit.

### Build and mapping

The Build screen starts a run (`POST /versions/{id}/builds`), polls `GET /builds/{run}` until it
settles and shows the steps as the pipeline records them (compile, drift, prepare, publish when the
domain materializes, load, finalize); a run still running when the screen opens is picked up, and
three failed status reads stop polling with a notice. The pre-build checklist reads the snapshot,
ontology, mapping completion, ontology checks and drift of the version.

The Mapping screen edits the version's mapping spec: map a class to a snapshot table and key,
bind attributes to columns from a dropdown, exclude properties, join relationships on a source and
target column, unmap, exclude everything unmapped, check drift (re-reads every mapped table from
the source, so it can take a while), export R2RML and ask the AI connection for suggestions. Local
names are resolved to IRIs through the version's ontology; every change is one `PUT
/versions/{id}/mapping`.

### The graph views

`Stage` draws every node-link map (Ontology, Mapping, Explore) with React Flow (`@xyflow/react`):
pan, zoom, fit, a minimap past 15 nodes, and edges routed with labels. Positions come from dagre
(`@dagrejs/dagre`): linked classes ranked top-to-bottom (left-to-right past 24 nodes, switchable),
classes with no relationship packed in a grid underneath. Past 30 nodes the map opens in focus mode,
showing the selected class and its neighbours (the ◎ tool shows everything); edge labels are shown
for the selected class's edges when there are more than 40. Explore keeps its own star layout
(`layout="given"`) around the chosen entity.

### The version mechanism

`GET /domains/{name}/versions/summary` is the one call behind the Versions and Overview screens: per
version it carries the content stats, mapping completion, last build and served triples, the current
review round (approvals count once per reviewer and restart when a version re-enters review) and the
draft's edit lease. The actions map one to one onto the backend:

| Action | Who | Backend |
|---|---|---|
| Take / release / force-take lease | builder / holder / admin | `POST` / `DELETE /versions/{id}/lease` |
| Submit for review, send back, publish, archive | builder / reviewer | `POST /versions/{id}/transition` (publishing needs the quorum) |
| Approve, reject with comment | reviewer | `POST /versions/{id}/reviews`; a rejection also transitions back to draft |
| Set active | reviewer | `POST /domains/{name}/active` |
| Create draft (from a version) | builder | `POST /domains/{name}/versions` |
| Delete draft (typed confirmation) | builder | `DELETE /versions/{id}` |
| Export bundle | anyone | `GET /domains/{name}/export?version_id=` |

`useLifecycle()` in `src/components/lifecycle.tsx` wraps all of them: it patches the domain state with
the response and turns backend refusals (quorum not met, lease held by someone else, another draft
exists) into toasts. The mock adapter enforces the same rules, so the screens behave identically in
`mock` and `rest` mode.
