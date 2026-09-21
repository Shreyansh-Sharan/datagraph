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
  components/ ui.tsx (buttons, cards, pills, tabs, dialog, toast, skeletons), icons.tsx, Stage.tsx (node-link map)
  screens/    Home (Ask + domain cards), Overview, Versions, Metadata, Ontology, Mapping, Rules, Quality, Build, Explore, Triples, Analytics, Settings, Tasks, Admin
  theme.css   design tokens and primitives
```

Routes (hash): `#/`, `#/tasks`, `#/admin`, `#/d/:domain[/screen]?v=3&cls=Sale&panel=data&table=fct_sales&tab=dq&entity=C-10482&q=…`.
Sub-state lives in the query string so every screen deep-links.

## Integration plan

`RestApi extends MockApi`: each method with a settled backend contract is overridden to call the API
(config, me, domains, versions, lifecycle, comments, audit, catalog, ontology, mapping status, table
preview, per-class SQL, builds with polling, search, entity, graph status, triples, test connection,
principals). Everything else still returns design data. Replace the fallbacks method by method; the
screens do not change. Backend shapes are documented in `docs/UI-BLUEPRINT.html` §8.
