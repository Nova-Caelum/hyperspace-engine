# `ui/dist/` provenance

This directory is a static build of the Caelos console (`Nova-Caelum/Caelos`)
at a pinned commit, shipped prebuilt inside this plugin so a user never needs
Node or a web toolchain installed. No Caelos source was modified to produce
this build.

- **Repo:** `Nova-Caelum/Caelos` (public), `origin/main` at the time of this
  build.
- **Pinned commit:** `21a60c453728cabf5fefaadbac4ff47251c6cd84` (short: `21a60c4`)
- **Built:** 2026-09-27T01:08:51Z
- **Node:** v22.23.1
- **npm:** 10.9.8
- **Commands:**
  ```sh
  git clone --no-checkout <repo> <build-dir>
  cd <build-dir>
  git checkout 21a60c4
  npm ci
  VITE_API_BASE_URL=. npm run build
  ```
  (`npm run build` = `npm run build:ui && vite build` — the `@nova-caelum/ui`
  workspace package builds first via panda/tsup, then the root Vite build.)
- **`VITE_API_BASE_URL`:** `.` (relative base — the same bundle works
  unmodified on any port the loopback door serves it from; an empty string
  would instead select Caelos's in-memory mock, per `src/app/App.tsx:198`'s
  `if (!API_BASE) return mockApi(...)`).
- **Bundle size:** 728K total (`du -sh ui/dist`)
- **File count:** 4 files
- **Largest three assets:**
  1. `assets/index-BQL6vRNH.js` — 528K
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
moment `main` moves past `21a60c4`. Re-run `ui/build.sh` (optionally with a
newer `--commit`) to refresh it; nothing here refreshes automatically.
