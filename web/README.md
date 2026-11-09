# web

React + Vite + TypeScript + Sigma.js/graphology UI (built on node:22-alpine, served by
nginx:1.27-alpine on port 3000, proxying `/api` to the api service).

The API contract is `src/api/openapi.json` (generated from the FastAPI app by
`scripts/export_openapi.py`; do not edit by hand). `npm run gen:api` regenerates the typed
`src/api/schema.d.ts`; `src/api/types.ts` aliases it and `src/api/client.ts` calls the relative `/api`.

```bash
npm ci
npm run dev:mock      # VITE_USE_MOCKS=1: whole API served by MSW (src/mocks, ~50 nodes); add ?empty for first run
npm run dev           # proxies /api to ATLAS_API_URL (default http://localhost:8000)
npm test              # vitest + Testing Library against the MSW handlers
npm run build         # tsc --noEmit, then vite build into dist/
```

## Layout

- `src/App.tsx` app shell: global/local scope, graph/list toggle, travel state, tray, shortcuts
- `src/components/graph/` Sigma canvas (ForceAtlas2 in a worker, dashed ghost-node program), lazy and WebGL-gated
- `src/components/` side panels, evidence dialog, Cmd+K palette, filters, list view, upload zone, progress tray
- `src/lib/` pure logic: GraphView to graphology (`graphModel`), filters, travel reducer
- `src/mocks/` in-memory backend shaped like the DTOs; used by tests and `dev:mock`

Shortcuts: Cmd/Ctrl+K search, Alt+Left/Right travel back/forward, Escape closes dialogs.
