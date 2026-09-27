# `ui/dist/` provenance

This directory is a static build of the Caelos console (`Nova-Caelum/Caelos`)
at a pinned commit, shipped prebuilt inside this plugin so a user never needs
Node or a web toolchain installed. No Caelos source was modified to produce
this build.

- **Repo:** `Nova-Caelum/Caelos` (public), `origin/main` at the time of this
  build.
- **Pinned commit:** `dfcb46d5e0402c049122dc443b85955caf37bc8d` (short: `dfcb46d`)
- **Built:** 2026-09-27T07:19:40Z
- **Node:** v22.23.1
- **npm:** 10.9.8
- **Commands:**
  ```sh
  git clone --no-checkout <repo> <build-dir>
  cd <build-dir>
  git checkout dfcb46d
  npm ci
  VITE_API_BASE_URL=. VITE_HUMAN_OWNER=user npm run build
  ```
  (`npm run build` = `npm run build:ui && vite build` — the `@nova-caelum/ui`
  workspace package builds first via panda/tsup, then the root Vite build.)
- **`VITE_API_BASE_URL`:** `.` (relative base — the same bundle works
  unmodified on any port the loopback door serves it from; an empty string
  would instead select Caelos's in-memory mock, per `src/app/App.tsx:198`'s
  `if (!API_BASE) return mockApi(...)`).
- **`VITE_HUMAN_OWNER`:** `user` — as of `dfcb46d`, Caelos's project-owner
  picker (`ProjectInfoTab`'s `ownerItems`) reads a build-time env var instead
  of a hardcoded literal (`src/app/App.tsx`'s `HUMAN_OWNER` const), pinned in
  Caelos's own `.env.production`/`.env.development` to the founder's own
  identity so Nova's own console is unaffected. This build passes
  `VITE_HUMAN_OWNER=user` explicitly — Vite gives an existing process-env
  value the highest priority over `.env` files, so this build never bakes a
  personal name into the shipped bundle regardless of what Caelos's own
  `.env.production` pins (verified: `probes/probe_no_vault_refs.py`'s
  denylist scan of the rebuilt `ui/` tree returns zero real findings).
  `probes/check_ui_build.py`'s reproducibility rebuild invokes this same
  `ui/build.sh`, so it inherits the identical env and produces a
  byte-identical bundle — the hashes do not diverge.
- **Bundle size:** 728K total (`du -sh ui/dist`)
- **File count:** 4 files
- **Largest three assets:**
  1. `assets/index-Cw8nVcU0.js` — 528K
  2. `assets/index-Bka4lujK.css` — 144K
  3. `assets/nova-caelum-wordmark-transparent-wusR2g40.png` — 52K

## Known finding — mock sentinel is bundled as dead code

`FOUNDRY_DEMO_PROJECT` (`src/app/App.tsx` ~line 74, `name: "Foundry
calibration"`) is a module-scope `export const` referenced unconditionally
in the top-level `App` component body (the `foundryMode ? ... : ps` ternary
at ~line 4177 evaluates the reference regardless of `foundryMode`'s runtime
value). Vite/Rollup's tree-shaking operates on module-graph reachability,
not on runtime branch outcomes, so the literal — including the string
`"Foundry calibration"` — is retained in the built JS even though this
production build always renders `<App />` with `foundryMode` defaulting to
`false` (`src/main.tsx`: `isFoundry && import.meta.env.DEV` gates the only
code path that ever sets `foundryMode={true}`, and `import.meta.env.DEV` is
`false` in a production build). The sentinel string being present in the
bundle is therefore **not** evidence the mock API path is reachable or used
at runtime. The runtime behavior — which endpoints the page actually
fetches — is verified empirically by `probes/ui_page_check.mjs`, which
records every `/api/*` and `/mcp` request the live page issues; that request
log is the evidence for "the relative base resolved, not the mock."

## Reproducing

Run `ui/build.sh` (optionally `--source <path-or-url>`, `--commit <sha>`,
`--out <dir>`) to rebuild from a fresh clone of the pinned commit and
replace `ui/dist/` (or another `--out` directory) wholesale.

**Honest caveat:** this bundle drifts from the live Caelos console the
moment `main` moves past `dfcb46d`. Re-run `ui/build.sh` (optionally with a
newer `--commit`) to refresh it; nothing here refreshes automatically.
