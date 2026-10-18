# TrustLayer extraction workbench

Additive React / TypeScript interface. The legacy Streamlit application is unchanged.

```sh
npm ci
npm run dev
npm test
npm run build
```

Open `http://127.0.0.1:5173/workbench/`. Start FastAPI on port 8000 separately;
Vite proxies `/v1` and `/docs` there. For a production build, restart FastAPI
after `npm run build`; it serves `dist/` at `/workbench/`.

The API-access field takes a caller-owned `tl_` key provisioned by the existing
backend. It is kept only in React memory. No provider credential, localStorage,
analytics, third-party fonts or automatic input persistence is used.

Quick and Deep both run local claim extraction in this release. The UI clearly
states that evidence research, factual/numerical checks and separate sycophancy
assessment have not run. It validates report structure, source offsets, counts
and nonpositive statuses before rendering. Unicode offsets use code points.

`npm test` checks the report trust boundary, Unicode highlights and readable
exports. `npm run test:e2e` runs browser integration tests against the actual
FastAPI extraction route. First install Python dependencies into the root `.venv`,
run `npm run build`, and install Chromium with `npx playwright install chromium`.
The test server binds only `127.0.0.1:8765`, overrides authentication with the
public `tl_browser_fixture` key, disables model/database access, and never loads
`.env`. It is a test harness, not a deployment mode. On Windows you may use an
already installed Chrome by setting `TRUSTLAYER_BROWSER_PATH` to its executable
path before running tests. On other systems the config uses `.venv/bin/python`.
Screenshots and traces go into ignored `test-results/`.

The offline GitHub Actions workflow runs Python regressions/evaluation, TypeScript
builds, frontend unit tests and the same browser tests without account secrets.

GSAP entrance/scroll animation, Lenis scrolling and a React Bits SpotlightCard
adaptation retain the violet/dark visual identity. System reduced-motion and an
in-page motion toggle disable decorative movement. Keyboard navigation, semantic
labels and responsive layouts support the actual inspection task.

See [third-party notices](THIRD_PARTY_NOTICES.md) for upstream source attribution
and licensing. No paid API or production deployment is needed for tests.
