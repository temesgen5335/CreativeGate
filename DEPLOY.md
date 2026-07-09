# Deploying CreativeGate

One always-on process serving the API and dashboard, with all state (SQLite,
artifact store, model cache) on a persistent volume. **Exactly one replica** —
SQLite has a single writer; this is by design until concurrent-write load
justifies the documented Postgres seam.

## Railway (recommended path)

The repo ships `railway.json` (Dockerfile build, `/health` health check,
1 replica) and a `Dockerfile`, so Railway needs only wiring:

1. **Create the service** from this GitHub repo. Railway detects the
   Dockerfile via `railway.json` automatically.
2. **Attach a volume** to the service, mount path `/data`.
3. **Set variables** (service → Variables):

   | Variable | Value |
   |---|---|
   | `CREATIVEGATE_DB` | `/data/creativegate.db` |
   | `CREATIVEGATE_ARTIFACT_DIR` | `/data/artifacts` |
   | `CREATIVEGATE_CACHE_DIR` | `/data/model-cache` |
   | `CREATIVEGATE_API_TOKEN` | a long random secret — **required before exposing the URL** |
   | `OPENAI_API_KEY` | optional; upgrades the judge rung from the keyless heuristic |

   `PORT` and `CREATIVEGATE_HOST` need no configuration: Railway injects
   `PORT`, and the image defaults the bind address to `0.0.0.0`.
4. **Deploy**, then generate a public domain (service → Settings →
   Networking). TLS is handled by Railway's edge.
5. **Open the dashboard once as** `https://<your-domain>/?token=<your-token>`
   — the SPA stores the token locally and sends it on every mutating call.
   Plain reads (verdict list, calibration view) work without it.

### Seeding demo data (optional)

For a populated dashboard before real traffic exists, run in the service
shell (or `railway ssh`):

```bash
creativegate demo --db /data/creativegate.db --out /tmp/demo_report.html
```

**Warning:** `demo` deletes and recreates the target database — it is for
initializing a demo, never for a database holding real verdicts. The
non-destructive alternative (ground truth + calibration, no sample verdicts):

```bash
creativegate seed-synthetic   # honors CREATIVEGATE_DB
```

### Verifying

- `https://<domain>/health` → `{"status": "ok", ..., "auth": "token"}` —
  if `auth` says `open`, the token variable isn't set; fix before sharing.
- Dashboard → Ingest → paste copy → Run gate → verdict should land in ~1s.

## Any other Docker host

```bash
docker build -t creativegate .
docker run -p 8000:8000 -v cg-data:/data \
  -e CREATIVEGATE_DB=/data/creativegate.db \
  -e CREATIVEGATE_ARTIFACT_DIR=/data/artifacts \
  -e CREATIVEGATE_CACHE_DIR=/data/model-cache \
  -e CREATIVEGATE_API_TOKEN=change-me \
  creativegate
```

Put TLS in front (Caddy/nginx/platform edge) — the bearer token must not
travel over plain HTTP across a network.

## Operational notes

- **Backups**: the SQLite file is the system of record, including the
  append-only calibration audit trail. Snapshot the volume or cron a copy of
  `$CREATIVEGATE_DB`.
- **Restarts are safe**: in-flight evaluation jobs are marked `interrupted`
  at startup (honest, re-submittable); trained predictor models reload from
  the cache dir instead of retraining.
- **Scaling**: do not raise replicas. The ceiling of this architecture is one
  node; past it, the next step is Postgres + a real queue (see
  `.claude/context.md` roadmap), not more replicas of this image.
- **CORS**: only needed if some *other* origin calls the API from a browser
  (`CREATIVEGATE_CORS_ORIGINS=https://app.example.com`). The bundled
  dashboard is same-origin and needs nothing.
