# Rate Tracker

Tracks central-bank rate decisions (US Fed, AU RBA), the economic data they
cite, and the forecasts economists & banks make — then scores those forecasters
on accuracy. Think "TipRanks for central banking".

## Architecture

Static-first. The public site is plain HTML/JS served from a CDN — no server on
the hot path, so almost no attack surface. Python scrapers run on a schedule
(GitHub Actions), emit validated JSON into `data/`, and Netlify auto-deploys.
Only two dynamic pieces exist, both tightly fenced:

- `scrape_url` — on-demand ingestion of a single URL from an **allowlisted
  domain** (SSRF-guarded), writing to a *staging* file for review.
- `leaderboard` — auth-gated (Supabase JWT verified server-side).

```
GitHub Actions (cron)
  └─ scrapers/*.py  → validate against schemas/ → data/*.json → commit (PR-gated)
       └─ Netlify auto-deploys static site/  (reads data/*.json)

PUBLIC:  site/index.html        timeline, reads data/*.json directly
GATED:   netlify/functions/     leaderboard (Supabase auth), scrape_url (allowlist)
```

## Security posture

- **Static by default.** Reach for a server function only when something can't
  be precomputed. Each function is justified individually.
- **All ingested content is untrusted.** Parse with real parsers, never
  `eval`/`exec`. Validate every record against `schemas/` before it lands.
- **Frontend renders JSON as text, never HTML** (`textContent`), plus a strict
  CSP via `site/_headers`. XSS can't get a foothold.
- **`scrape_url` is SSRF-guarded**: https-only, domain allowlist, private-IP
  blocking, size/timeout caps, no redirects, rate-limited. Writes to staging,
  never straight to live scores.
- **Secrets never in the repo** — GitHub Actions secrets / Netlify env only.
  Supabase service-role key is server-only; the anon key is public by design.
- **Data is append-only & timestamped.** Forecasts are never retroactively
  edited — corrections are new records. Every record carries `provenance`.
  Git is the audit log.

## Data model

See `schemas/`. Every record embeds a `provenance` block (source URL, scrape
time, parser + version, ingest method, content hash). Core entities:

| Entity            | File                          | What it is                          |
|-------------------|-------------------------------|-------------------------------------|
| Decision          | `decision.schema.json`        | A rate decision (raise/hold/cut)    |
| Indicator         | `indicator.schema.json`       | An economic data point (CPI, etc.)  |
| Forecaster        | `forecaster.schema.json`      | A bank or individual economist      |
| Forecast          | `forecast.schema.json`        | A prediction: point/path (rates) or indicator (inflation/jobs) |
| Score             | `score.schema.json`           | Computed accuracy for one forecast  |
| Forecaster rollup | `forecaster_rollup.schema.json` | Aggregate accuracy per forecaster |

## Status

- [x] Step 1 — schemas, validation, provenance contract, mock data
- [x] Step 2 — static timeline frontend
- [x] Step 3 — real scrapers (Fed, RBA, FRED, ABS) on Actions cron
- [x] Step 4 — forecast scraper + scorer (point + path, on-pace tracker)
- [x] Step 5 — `scrape_url` function (auth-gated, allowlist + SSRF guards)
- [x] Step 6 — Supabase auth + leaderboard
- [ ] Step 7 — X + Reddit (designed, stubbed, disabled)

## Serverless functions (Node, not Python)

Netlify Functions run Node/Go, not Python — so the always-on endpoints live in
`netlify/functions/*.mjs` while the Python scrapers run on GitHub Actions cron.
Both sides share **one** fetch allowlist (`config/allowed_domains.json`) so the
trust boundary can't drift.

- `scrape_url.mjs` — signed-in users submit a source URL. Requires a valid
  Supabase JWT, runs the same SSRF guards as the Python fetcher, and **stages**
  the result in Supabase (`status='pending'`) for review — never live data.
- `leaderboard.mjs` — members-only ranked accuracy table. Requires a valid JWT
  and reads `rollups.json` (bundled with the function, **not** published as a
  static file) so the leaderboard is genuinely gated, not just hidden in the UI.

Auth uses Supabase GoTrue's REST API directly (`site/auth.js`) — no SDK, so
nothing external loads and the strict CSP holds. The public timeline serves
decisions/indicators/forecasts/forecasters/scores; only the aggregate rollups
are gated.

Required env vars (Netlify dashboard / Actions secrets — never in the repo):

| Var | Used by | Notes |
|-----|---------|-------|
| `SUPABASE_URL` | functions | Project URL |
| `SUPABASE_JWT_SECRET` | functions | Verifies user tokens (server-only) |
| `SUPABASE_SERVICE_KEY` | functions | Staging writes; bypasses RLS (server-only) |
| `SUPABASE_ANON_KEY` | frontend | Public by design (login flow, Step 6) |

Apply `supabase/schema.sql` to create the `submissions` table (RLS deny-all,
users can only insert/read their own rows).

```bash
node --test tests/js/*.test.mjs   # function security tests (SSRF, JWT)
```

## Development

```bash
pip install -r requirements.txt
python -m scrapers.validate data/   # validate all data files against schemas
pytest                              # run tests
```
