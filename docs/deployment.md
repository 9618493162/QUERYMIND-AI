# Production deployment runbook

Single-host deployment with TLS terminated by Caddy. Everything the browser
talks to is **one origin**, which is what makes the session cookie and the CSRF
double-submit token work (the client uses `credentials: 'same-origin'` and
relative `/api/...` paths).

```
Browser ──HTTPS(443)──> Caddy ──/api/*──> FastAPI (uvicorn:8001) ──> PostgreSQL
                          │                     │
                          └──/* ──> React SPA   └──> Ollama (qwen2.5-coder:7b)
                                    (/srv)
```

Only Caddy publishes ports. PostgreSQL, Ollama and FastAPI are reachable on the
internal Docker network only.

| File | Purpose |
| --- | --- |
| [docker-compose.prod.yml](../docker-compose.prod.yml) | production stack (this runbook) |
| [docker-compose.yml](../docker-compose.yml) | **development only**: public DB ports, sample analytics data |
| [backend/Dockerfile](../backend/Dockerfile) | FastAPI + uvicorn image |
| [docker/web/Dockerfile](../docker/web/Dockerfile) | Vite build → Caddy runtime |
| [docker/caddy/Caddyfile](../docker/caddy/Caddyfile) | TLS, SPA fallback, `/api/*` proxy, body cap |
| [.env.production.example](../.env.production.example) | template for the secrets file |

---

## 1. Resource requirements

| Component | RAM | Disk | CPU | Notes |
| --- | --- | --- | --- | --- |
| FastAPI backend | 256–512 MB | ~350 MB (image) | 0.25–1 vCPU | pandas/sqlglot imports dominate cold start |
| PostgreSQL 16 | 512 MB–1 GB | 10 GB+ | 0.25 vCPU | metadata only (users, connections, history) |
| Ollama + qwen2.5-coder:7b | **8 GB minimum**, 12–16 GB comfortable | ~5 GB (model) | 2+ vCPU | CPU inference is slow but works; a GPU is much faster |
| Caddy | ~50 MB | ~1 GB (certificates/state) | minimal | terminates TLS, serves static assets |

**Recommended host: 4 vCPU, 16 GB RAM, 40 GB SSD.** A 2 vCPU / 8 GB host is the
practical minimum and only if the model runs alone. CPU inference of a 7B model
takes seconds per generated query; `AI_TIMEOUT_SECONDS=180` is set for that
reason. No GPU is required.

## 2. Prerequisites

1. A host with Docker Engine and Compose v2 (`docker compose version`).
2. A DNS `A`/`AAAA` record for `DOMAIN` pointing at the host.
3. Ports 80 and 443 free and reachable from the internet (Caddy needs 80 for the
   ACME HTTP challenge and the HTTP→HTTPS redirect).
4. The repository checked out on the host (or the images built elsewhere).

## 3. First deployment

```bash
# 1. Secrets. This file is git-ignored; never commit it and never bake it into
#    an image.
cp .env.production.example .env.production
$EDITOR .env.production          # DOMAIN, ACME_EMAIL, APP_SECRET_KEY,
                                 # ENCRYPTION_KEY, POSTGRES_PASSWORD, FRONTEND_ORIGIN

# 2. Build the images.
docker compose --env-file .env.production -f docker-compose.prod.yml build

# 3. Apply database migrations ONCE, explicitly. (Never automatic: see §5.)
docker compose --env-file .env.production -f docker-compose.prod.yml \
  --profile tools run --rm migrate

# 4. Start the stack.
docker compose --env-file .env.production -f docker-compose.prod.yml up -d

# 5. Pull the real model into the Ollama volume (one-time, ~4.7 GB).
docker compose --env-file .env.production -f docker-compose.prod.yml \
  exec ollama ollama pull qwen2.5-coder:7b

# 6. Verify.
curl -fsS https://$DOMAIN/api/health            # liveness
curl -fsS https://$DOMAIN/api/health/ready      # readiness (503 if DB is down)
curl -fsS https://$DOMAIN/api/health/ai         # real provider + model
```

`FRONTEND_ORIGIN` must be exactly the browser-visible origin
(`https://<DOMAIN>`) — startup validation rejects anything else in production.

## 4. Health endpoints and probes

| Endpoint | Meaning | HTTP | Use it for |
| --- | --- | --- | --- |
| `GET /api/health` | **liveness** — the process answers | always 200 | container healthcheck, restart decisions |
| `GET /api/health/ready` | **readiness** — metadata DB reachable | 200 / **503** | load balancer / proxy routing decisions |
| `GET /api/health/ai` | provider diagnostics (cached ~15 s) | 200 | operator diagnostics; **never** liveness/readiness |

Liveness deliberately does not touch the database: a slow or restarting
PostgreSQL must not cause the orchestrator to kill a healthy app container.
Readiness is the probe that reports a database outage, without restarting
anything.

## 5. Migrations

Migrations are **never** applied automatically on startup. The `migrate`
service exists only under the `tools` profile, so `up` cannot alter the schema:

```bash
# Deploy procedure: backup → migrate → start
docker compose --env-file .env.production -f docker-compose.prod.yml \
  --profile tools run --rm migrate
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

Run it once per deployment, from a single instance, before rolling new
containers. `alembic check` (used by CI) fails on schema drift, so migrations
and models cannot silently diverge.

## 6. Trusted proxy handling

`X-Forwarded-For` is a client-supplied header. The rate limiter only believes it
when the immediate peer is a configured trusted proxy
(`TRUSTED_PROXY_IPS`, set to the compose subnet `172.28.0.0/24` by default);
otherwise the header is ignored and the direct peer address is used. When the
peer *is* trusted, the chain is walked right-to-left (the direction our own
proxy appends) and the first untrusted address wins — so a client that prepends
a fake IP cannot rotate its rate-limit bucket.

If `172.28.0.0/24` is already used on the host, set `COMPOSE_SUBNET` in
`.env.production`; the same value feeds both the network definition and
`TRUSTED_PROXY_IPS`.

## 7. Secrets

- Live in `.env.production` (git-ignored) or your platform's secret manager.
- `.dockerignore` excludes every `.env*` file, so secrets cannot enter an image
  layer; only the checked-in `.example` templates ship.
- Startup validation refuses production with a placeholder `APP_SECRET_KEY`, a
  non-HTTPS `FRONTEND_ORIGIN`, a wildcard/localhost origin, non-Secure cookies,
  a non-TLS remote `DATABASE_URL`, or a missing `ENCRYPTION_KEY`.
- Nothing logs credentials: exception logging redacts passwords, connection
  strings, tokens, cookies and bound SQL parameters (see
  [errors.py](../backend/app/core/errors.py)).

## 8. Backups

The compose stack keeps PostgreSQL data in the `querymind_postgres_data` volume.
Back that up out-of-band, for example:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  exec postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > backup-$(date +%F).sql.gz
```

Schedule it, store it off-host, and test a restore. **Automated backups are not
configured by this change** — see §11.

## 9. Logs

- Application logs go to stdout/stderr (`LOG_LEVEL`, default `INFO`).
- Every response carries `X-Request-ID` (a caller-supplied id is reused only
  when it looks like an id) and unhandled exceptions are logged as one JSON
  object containing that id, the path, the exception type, a redacted message
  and a redacted traceback.
- Caddy logs JSON to stderr.

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f backend
```

## 10. Verifying a deployment

```bash
# Inside the repo, against the deployed origin (real model, real database):
cd backend
./.venv/Scripts/python.exe scripts/live_e2e_check.py --base-url https://DOMAIN
./.venv/Scripts/python.exe scripts/live_failure_check.py --base-url https://DOMAIN
```

These scripts register a throwaway user, connect to a real database, generate
SQL with the real model, execute it read-only and cross-check the rows against
an independently executed query. The failure script proves an unreachable
database/model produces real errors and no fabricated SQL.

Also confirm, in a browser: the session cookie is `Secure` + `HttpOnly`,
`/api/*` without a CSRF token returns 403, and the SPA deep links
(`/app/workspace`) load directly.

## 11. Remaining limitations

- **No automated backups or off-host storage** are configured here.
- **Single instance only** for correctness: rate limiting and schema caches are
  in-process, and session/CSRF state is fine (cookies), but the limiter needs a
  shared store before scaling out ([rate-limiting.md](rate-limiting.md)).
- **No monitoring/alerting integration** (no error tracker, no metrics
  endpoint); the JSON error log and `/api/health/ready` are the hooks to wire up.
- **Ollama runs on the same host**; a GPU host would be dramatically faster.
- The production image installs `requirements.txt` as-is, which includes
  `pytest`/`pytest-asyncio`; splitting test dependencies is a follow-up.
- HTTPS/ACME assumes Caddy can complete the HTTP-01 challenge (port 80 open, DNS
  resolving); a DNS-01 setup is out of scope.
