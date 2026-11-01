# Production deployment checklist

Use this checklist for every environment that real people will use. It assumes
the stack from `docker-compose.yml` (PostgreSQL, Redis, API, CV worker, nginx
dashboard) but applies equally to a Kubernetes/VM deployment.

The order matters: configuration first, then secrets, then data, then
observability, then the go-live smoke test.

---

## 1. Configuration

| Setting | Production value | Why |
| --- | --- | --- |
| `ENVIRONMENT` | `production` | enables the startup security guard |
| `DEBUG` | `false` | **fatal** in production, leaks internals |
| `SECRET_KEY` | random 64 hex chars (`openssl rand -hex 32`) | signs JWTs; placeholder/short keys are **fatal** |
| `DATABASE_URL` | `postgresql+asyncpg://…` | SQLite is a warning, not production-grade |
| `REDIS_ENABLED` | `true` | cross-process WebSocket fan-out + rate limits |
| `CORS_ORIGINS` | `["https://gates.example.com"]` | wildcard is **fatal** in production |
| `TRUSTED_HOSTS` | `["gates.example.com","api.internal"]` | blocks Host-header attacks |
| `MEDIA_ROOT` | `/data/media` (volume) | snapshots must survive container restarts |
| `CV_MODE` | `real` | `mock` means decisions are simulated (warning) |
| `RETENTION_DAYS` | 90–365 | detections + snapshots |
| `RETENTION_ACCESS_LOG_DAYS` | 730+ | audit trail (keep per your legal policy) |
| `MAINTENANCE_ENABLED` | `true` (or cron) | expiry + retention |

The API refuses to boot (`RuntimeError` at startup) when `ENVIRONMENT=production`
and any of these is wrong: placeholder/short `SECRET_KEY`, `DEBUG=true`,
wildcard `CORS_ORIGINS`. Everything else is logged as a warning at boot — read
them:

```
WARNING app.main | Configuration: CV_MODE=mock: gate decisions are simulated, not from real cameras
```

---

## 2. Secrets

* `SECRET_KEY` — rotation invalidates every session (all refresh tokens stop
  working); schedule it and announce it.
* `POSTGRES_PASSWORD`, `REDIS_PASSWORD` — inject from a secret manager or the
  orchestrator, never commit `.env`.
* RTSP credentials live inside `cameras.source_url`. Use read-only camera
  accounts, restrict DB access, and rotate with a `PATCH /cameras/{id}`.
* Barrier secrets: `BARRIER_WEBHOOK_SECRET` / `barrier.webhook.secret`,
  MQTT password, GPIO (none). These are masked (`********`) by the API and
  round-trip safely on `PATCH /compounds/{id}/settings`.
* Default demo passwords (`Admin@12345`, …) must be changed or the demo users
  deleted before go-live.

```bash
# rotate any user's password (admin)
curl -X POST localhost:8000/api/v1/users/$USER_ID/reset-password \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"new_password": "'"$(openssl rand -base64 24)"'"}'

# change your own password
curl -X POST localhost:8000/api/v1/auth/change-password \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"current_password": "…", "new_password": "…"}'
```

---

## 3. Database and data

1. `alembic upgrade head` (the `api` container runs it on start; run it
   manually in blue/green deployments before switching traffic).
2. `python -m app.cli create-admin` for the first real administrator.
3. Do **not** run `SEED_DEMO_DATA=true` in production.
4. Backups: nightly `pg_dump` + the media volume; test a restore quarterly.
5. Retention: the in-process loop runs every `MAINTENANCE_INTERVAL_SECONDS`,
   in batches (`RETENTION_BATCH_SIZE`, `RETENTION_MAX_BATCHES`) so a large
   backlog drains over several cycles. Prefer disabling the loop and running
   `python -m app.tasks.maintenance --once` from cron/systemd in multi-replica
   deployments (avoid N replicas pruning concurrently).
6. Check the backlog before a big cleanup:

```bash
python -m app.tasks.maintenance --dry-run
```

---

## 4. Network & TLS

* Terminate TLS at the reverse proxy (nginx/Traefik/cloud LB) and forward
  `X-Forwarded-For` / `X-Forwarded-Proto`. Run uvicorn with `--proxy-headers`.
* The dashboard container (`nginx-unprivileged`, port **8080**) proxies `/api/`
  and `/media/`; the WebSocket route needs `Upgrade`/`Connection` headers and a
  long read timeout (the shipped `frontend/nginx.conf` already does this).
* Expose **only** the dashboard publicly. `/metrics` and `/health/*` should be
  reachable from the monitoring network, not the internet:

```nginx
location = /metrics { allow 10.0.0.0/8; deny all; proxy_pass http://gatevision_api; }
```

* Cameras stay on their own VLAN; the CV worker needs outbound RTSP to them.

---

## 5. Container hardening

Both images are already non-root and slim:

| Image | Runtime user | Notes |
| --- | --- | --- |
| `gatevision-api` | uid 10001 | multi-stage build, no compilers/curl, Python healthcheck |
| `gatevision-cv` | uid 10001 | adds `ffmpeg` + the CV wheels, ~2–3 GB |
| `gatevision-frontend` | uid 101 (`nginx-unprivileged`) | listens on 8080 |

Recommended runtime flags:

```yaml
read_only: true
tmpfs: ["/tmp"]
security_opt: ["no-new-privileges:true"]
cap_drop: ["ALL"]
```

The API writes only to `/data/media` (mount a volume) and `/tmp`; the nginx
container needs no writable paths beyond `/tmp`.

---

## 6. Observability

**Health probes**

| Endpoint | Use | Behaviour |
| --- | --- | --- |
| `GET /api/v1/health` | liveness | always 200 when the process is up |
| `GET /api/v1/health/live` | liveness alias | same |
| `GET /api/v1/health/ready` | readiness | 503 only when the DB (or enabled Redis) is down; `checks` reports vision engine, barrier driver and maintenance state, `warnings` names soft problems |

Do **not** gate readiness on the CV engine: a missing model must not take the
dashboard and the audit trail offline.

**Metrics** — `GET /metrics` (Prometheus text format):

| Metric | Type | Watch for |
| --- | --- | --- |
| `gatevision_http_requests_total{method,route,status}` | counter | 5xx ratio, per-route latency |
| `gatevision_http_request_duration_seconds_bucket` | histogram | p95 > 1 s on `/cv/analyze` |
| `gatevision_access_decisions_total{decision,reason_code}` | counter | spike of `unknown` or `blacklist_*` |
| `gatevision_barrier_commands_total{driver,action,accepted}` | counter | `accepted="false"` > 0 |
| `gatevision_vision_results_total{outcome}` | counter | `none` growing = cameras/lens problem |
| `gatevision_face_enrollments_total{result}` | counter | `rejected` growth = bad enrolment workflow |
| `gatevision_cv_engine_ready` | gauge | `0` = models not loaded |
| `gatevision_face_gallery_entries` | gauge | drops unexpectedly = gallery reload failed |
| `gatevision_maintenance_last_success_timestamp_seconds` | gauge | stale = scheduler stuck |
| `gatevision_maintenance_purged_total{kind}` | counter | retention actually running |

Example scrape config and alerts:

```yaml
scrape_configs:
  - job_name: gatevision
    metrics_path: /metrics
    static_configs: [{ targets: ["api:8000"] }]
```

```yaml
groups:
- name: gatevision
  rules:
  - alert: VisionEngineNotReady
    expr: gatevision_cv_engine_ready == 0 and on() (gatevision_app_info{cv_mode="real"} == 1)
    for: 10m
  - alert: BarrierCommandFailing
    expr: increase(gatevision_barrier_commands_total{accepted="false"}[15m]) > 0
  - alert: ApiErrorRate
    expr: sum(rate(gatevision_http_requests_total{status=~"5.."}[5m])) > 0.5
  - alert: MaintenanceStalled
    expr: time() - gatevision_maintenance_last_success_timestamp_seconds > 7200
```

**Logs** — structured (`LOG_FORMAT=json` in production). Every barrier command
logs driver, latency and outcome; every request logs method, path, status and
duration with a request id (`X-Request-ID` echoes it back).

---

## 7. Go-live smoke test

```bash
BASE=https://gates.example.com/api/v1
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"…"}' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

curl -s $BASE/health/ready | jq '.status, .checks.vision, .warnings'
curl -s $BASE/cv/status -H "$AUTH" | jq '{mode, engine_ready, models_loaded, face_gallery_size}'
curl -s $BASE/cv/camera-health -H "$AUTH" | jq
curl -s $BASE/cv/actuators -H "$AUTH" | jq '.compounds[] | {compound_name, driver, health}'
curl -s -X POST $BASE/cv/actuators/test -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"gate_id":"'$GATE_ID'","action":"open"}' | jq
curl -s $BASE/analytics/dashboard -H "$AUTH" | jq '.overview, .barrier_failures'
curl -s https://gates.example.com/ -o /dev/null -w 'dashboard %{http_code}\n'
```

Then open the dashboard and confirm:

- [ ] Login works for admin, officer and a resident
- [ ] Arabic/English switch flips the layout to RTL (ع)
- [ ] Live monitor shows real detections with snapshots
- [ ] A known plate opens the barrier; an unknown plate asks for review
- [ ] The review queue can be resolved and appears in the access log
- [ ] `/metrics` is scraped by Prometheus and alerts evaluate
- [ ] A manual backup of PostgreSQL + media volume exists

---

## 8. Rollback

1. Keep the previous image tags (`gatevision-api:<git-sha>`); roll back with
   `docker compose up -d --no-deps api frontend`.
2. Alembic migrations are forward-only here: snapshot the DB before
   `alembic upgrade head` so you can restore instead of downgrading.
3. If only the barrier misbehaves, switch the compound back to the simulator
   (`PATCH /compounds/{id}/settings {"barrier":{"driver":"simulator"}}`) or
   disable automation (`access.auto_open_barrier=false`) — no redeploy needed.
