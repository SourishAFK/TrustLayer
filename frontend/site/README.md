# TrustLayer website

The public site: a cinematic landing page, an audience-tagged sign-up page, the live
demo, and a printable sample Bot Check-up report. Static files; it talks to the API
only through `POST /v1/leads` and `POST /v1/demo/verify/stream`.

| Page | Path | What it does |
| --- | --- | --- |
| Home | `/` | Hero with the 3D Trust Clock, cited incidents, one section per audience, how a check works, the pushback test, the Trust Clock, benchmark proof, the vision |
| Free check | `/check/?for=product-teams\|documents\|support-bots\|general` | Sign-up form. Saves the audience tag, the page and campaign the visitor arrived from, and whether they would pay for a full check; nothing confidential |
| Live demo | `/demo/?preset=answer\|document\|support` | Streams a real Quick Check. When the demo is off or busy, replays a labelled recording of the same example |
| Sample report | `/report/sample/` | A fictional lender's Bot Check-up, built from `src/pages/report/sample-report.json`; prints as a clean document |

## Run it

```bash
cd frontend/site
npm ci
npm run dev          # http://127.0.0.1:5173, proxies /v1 to the API on :8000
npm test             # unit tests (vitest)
npm run build        # type-check + production build into dist/
npm run test:e2e     # builds, serves dist/ and runs the browser tests with the API mocked
```

If Playwright's own browser is not installed, point it at any Chromium:
`TRUSTLAYER_BROWSER_PATH=/path/to/chrome npm run test:e2e`.

To try the demo against a local API, start the API with `TRUSTLAYER_PUBLIC_DEMO=true`.
Sign-ups need the API's database; count them per audience with
`python -m backend.admin leads`.

## Deploy

Any static host works. Render's blueprint (`render.yaml`) already has a `trustlayer-site`
service. Two build-time settings:

| Setting | Example | Why |
| --- | --- | --- |
| `VITE_API_BASE` | `https://trustlayer-api.onrender.com` | Where the API lives. Leave empty when the site and API share a domain |
| `SITE_URL` | `https://your-domain.example` | Makes the link-preview image absolute; LinkedIn, X and WhatsApp ignore relative ones. The build warns when it is missing |
| `VITE_CONTACT_EMAIL` | `hello@your-domain.example` | If a sign-up cannot be sent, the form offers this address with the visitor's details filled in, plus a copy button, so no lead is lost |

On the API, allow the site's origin in `TRUSTLAYER_CORS_ORIGINS`, set `TRUSTLAYER_IP_SALT`,
and turn on `TRUSTLAYER_PUBLIC_DEMO` only with a key that can take the traffic
(`TRUSTLAYER_DEMO_DAILY_LIMIT` caps it).

## Refresh the demo recordings

The fallback replays in `src/pages/demo/recorded/` are real engine runs of the examples
in `src/pages/demo/presets.json`. After changing an example or the engine, re-record from
the repository root:

```bash
.venv/Scripts/python.exe frontend/site/record_demo.py            # all three, about 3 minutes
.venv/Scripts/python.exe frontend/site/record_demo.py support    # just one
```

A run whose AI calls fail (quota, outage) is not saved, so a bad day at a provider never
becomes the demo.

## How it is built

- **Vite + React 19 + TypeScript**, one HTML entry per page (no client router).
- **Tailwind CSS 4** for layout; the look lives in `src/styles.css`: color and type
  tokens, glass panels, animated "beam" borders, cursor spotlights, aurora glows, grain.
- **GSAP** (ScrollTrigger, SplitText, ScrambleText, DrawSVG) with **Lenis** smooth
  scrolling. Story sections are sticky: on desktop each animation follows the scroll;
  on phones it plays once; with reduced motion the final state shows, still.
- **three.js** draws the background (`src/three/field.ts`): thousands of claim points on
  a clock face, checked by a sweeping hand. Most light up cyan, a few flare ember. It
  morphs into a globe for the "trust grade for every AI" section. It loads after first
  paint, caps the pixel ratio, pauses in hidden tabs, and falls back to CSS if WebGL is
  missing.
- **Charts** are hand-written SVG and HTML following the dataviz rules: thin marks, a
  table view, hover and keyboard tooltips, labels in ink. The verdict colors passed the
  palette validator in dark and light mode, and every mark carries a text label.

## Honesty rules for this site

- Every number links to its source (`src/lib/content.ts`, listed in the footer).
- Every illustration says so, and invented names are labelled invented.
- The sample report is marked as fictional on screen and in print.
- Demo recordings say they are recordings, with their date.
- Benchmark numbers come from `evaluation/results/` with their caveats beside them.
