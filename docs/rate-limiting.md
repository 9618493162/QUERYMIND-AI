# Rate limiting

QueryMind ships a small, dependency-free rate limiter in
[`backend/app/core/rate_limit.py`](../backend/app/core/rate_limit.py). This
document describes exactly what it does today, where it stops being sufficient,
and what to do if you deploy more than one instance. No new service (Redis or
otherwise) is introduced by this change — the recommendation below is a plan,
not a dependency.

## Behaviour

| Property | Value |
| --- | --- |
| Algorithm | Fixed window, one minute per key |
| Storage | In-process Python `dict` (`defaultdict(list)` of timestamps) |
| Key | `"{bucket}:{client_key}"` |
| Client key | First entry of `X-Forwarded-For`, else the direct peer IP |
| Limit exceeded | `429` with `{"error": {"code": "rate_limited"}}` |
| Synchronisation | A module-level `threading.Lock` around the counter |

Buckets currently in use:

| Bucket | Call site | Default limit / minute |
| --- | --- | --- |
| `auth-register` | `POST /api/auth/register` | `AUTH_RATE_LIMIT_PER_MINUTE` (10) |
| `auth-login` | `POST /api/auth/login` | `AUTH_RATE_LIMIT_PER_MINUTE` (10) |
| `query-generate` | `POST /api/query/generate`, conversation messages | `QUERY_RATE_LIMIT_PER_MINUTE` (30) |
| `query-execute` | `POST /api/query/execute` | `QUERY_RATE_LIMIT_PER_MINUTE` (30) |
| `conn-test` | `POST /api/connections/test` | 30 (hard-coded) |
| `csv-upload` | `POST /api/uploads`, `POST /api/uploads/preview` | 10 (hard-coded) |

A limit of `0` (or negative) disables limiting for that bucket. `reset()` is
provided for tests and clears every counter.

## Limitations

These are properties of the current implementation, not bugs:

1. **Per-process, not per-application.** Counters live in the memory of a
   single Python process. Two `uvicorn` workers, a second container, or a
   rolling deploy each carry an independent counter.
2. **Effective limit multiplies with instances.** With `N` workers/instances, a
   client can make roughly `N × limit_per_minute` requests before the first
   worker rejects one — the real limit is not enforced application-wide.
3. **No shared state, so no coordination.** There is no way for instance A to
   know that instance B already saw 9 login attempts from the same IP.
4. **Unbounded key cardinality.** The hit map is never evicted by key; it grows
   with the number of distinct client keys seen since start. Under high
   cardinality or spoofed `X-Forwarded-For` values, memory grows until the
   process restarts.
5. **`X-Forwarded-For` is trusted.** The client key comes from that header when
   present, so a client that can set it can also rotate its bucket key. Only run
   behind a proxy that overwrites/validates the header.
6. **Fixed window, not sliding.** A client can burst twice at a window boundary
   (up to `2 × limit` in a short period).

## When the current limiter is enough

- A single instance / single worker deployment.
- Local development and the test suite.
- A "defence in depth" layer behind a proxy or CDN that already throttles by IP.

## Recommended approach if you plan a distributed deployment

Do **not** rely on the in-process limiter for correctness once more than one
instance serves traffic. In priority order:

1. **Throttle at the edge** (CDN, load balancer, or reverse proxy) where the
   limit can be applied to real client IPs before requests reach the app. This
   is the least code and needs no new application dependency.
2. **Move the counter to a shared store** — for example Redis with an atomic
   `INCR` + `EXPIRE`, a sliding-window or token-bucket script, or a managed
   equivalent — and keep the same interface: every call site already goes
   through `rate_limit(request, bucket, limit_per_minute)`.
3. **If rate limiting is a security control** (for example brute-force
   protection on `auth-login`), also add per-account lockout/countermeasures
   that do not depend on the client IP at all.

Introduce a shared store only when the deployment actually needs it, and when
you do, prefer a service the stack already runs. Middleware such as
`slowapi`/`limits` can front Redis, but the decision to add that dependency
should come with the multi-instance requirement — not before.

## Verifying the current behaviour locally

```bash
cd backend
# 15 logins against the real API: the tail of the list is 429s
./.venv/Scripts/python.exe -m pytest app/tests/test_auth.py -q -k rate_limit
```
