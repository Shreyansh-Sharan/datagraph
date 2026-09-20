# ontoforge design system

**Strategy:** restrained. Tinted neutrals with one accent (deep green, `--accent`) for primary actions, selection and state; semantic colors (info/ok/warn/danger) only for status. Dark and light themes follow the OS; both are first-class.

**Type:** one family (system sans stack), fixed rem scale 12 / 13 / 14 / 16 / 20 (ratio ~1.15), weight for hierarchy. Mono for IRIs, SQL, code.

**Spacing:** 4px scale (`--s1`..`--s6`). Radius 4px controls, 6px panels. No shadows; structure by 1px borders and surface steps (`--bg` < `--surface` < `--surface-2`).

**Layout:** top bar (brand, breadcrumb, identity) + left section nav within a domain + content. Content is a task area, not a card grid: page head with title, one-line intent, primary actions right-aligned; then the working surface (table, split panel, graph stage).

**Components:** buttons (default / primary / danger / ghost / sm), inputs, selects, textareas, tables (dense, hover row), badges (status vocabulary: draft, in review, published, archived, running, succeeded, failed, complete, partial, unmapped), toasts (bottom-right, 4.5s), native `<dialog>` for confirmations and short forms, skeleton loaders, empty states that say what to do next.

**Graph stage:** WebGL (sigma.js + graphology, vendored, MIT). ForceAtlas2 layout with noverlap, nodes colored by class (stable palette, legend), size by degree, labels by zoom density, hover highlights the neighbourhood and dims the rest, click selects and opens the detail panel, double-click expands, controls: zoom in/out/fit, layout toggle, color by class / community.

**Motion:** 150–200ms ease-out on hover/selection/panel changes; none on page load; reduced-motion respected.
