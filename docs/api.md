# GateVision API Reference

* Base URL: `http://localhost:8000/api/v1` (Docker: `http://localhost:8000/api/v1`, dashboard proxy: `/api/v1`)
* Interactive documentation: `/docs` (Swagger UI) and `/redoc`
* Content type: `application/json` unless noted
* All timestamps are UTC ISO-8601 strings.

---

## 1. Authentication

GateVision issues a short-lived **access token** and a long-lived **refresh token**
(HS256 JWTs). Both are returned by the login endpoint together with the user profile.

| Method | Path | Body | Notes |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | `{email, password}` | Returns `TokenPair` |
| `POST` | `/auth/token` | form `username`, `password` | OAuth2 password form for Swagger |
| `POST` | `/auth/refresh` | `{refresh_token}` | Rotates the pair |
| `GET` | `/auth/me` | – | Current profile incl. `resident_id` |
| `POST` | `/auth/change-password` | `{current_password, new_password}` | Min 8 chars, letter + digit |
| `POST` | `/auth/logout` | – | Stateless; audit only |

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@gatevision.app","password":"Admin@12345"}' | jq -r .access_token)

curl -s http://localhost:8000/api/v1/analytics/overview \
  -H "Authorization: Bearer $TOKEN" | jq
```

Send the access token as `Authorization: Bearer <token>`. A `401` with
`code=token_expired` means the client should call `/auth/refresh` (the bundled
dashboard does this automatically, single-flight).

**Roles:** `admin` (all compounds), `security_officer` (own compound, gates/cameras/
visitors/blacklist/overrides), `resident` (own household, own visitors, own logs).

---

## 2. Conventions

### Pagination

Every list endpoint returns:

```json
{
  "items": [],
  "total": 153,
  "page": 1,
  "page_size": 25,
  "pages": 7
}
```

Query parameters: `page` (≥1, default 1), `page_size` (1–200, default 25),
`sort_by` (endpoint-specific), `sort_dir` (`asc` | `desc`).

### Errors

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request payload is invalid",
    "details": [{"field": "plate_number", "message": "Field required"}],
    "request_id": "72c0f9fe52d5494eadb98428550ef3ce"
  }
}
```

| HTTP | `code` | Meaning |
| --- | --- | --- |
| 400 | `bad_request` | Semantically invalid request |
| 401 | `unauthorized` / `token_expired` | Missing or expired credentials |
| 403 | `permission_denied` | Role or compound scope violation |
| 404 | `not_found` | Unknown id inside the caller's scope |
| 409 | `conflict` | Duplicate plate / email / unit |
| 422 | `validation_error` | Pydantic validation failure |
| 429 | `rate_limited` | Too many login attempts |
| 503 | `vision_unavailable` | CV engine could not process the image |

Every response includes `X-Request-ID`; include it in bug reports.

### Common query filters

Most list endpoints accept `search` (case-insensitive partial match), `status`,
`start` / `end` (ISO datetimes) and `compound_id` (admin only — other roles are
pinned to their own compound).

---

## 3. Resources

### 3.1 Health

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness + version |
| `GET` | `/health/ready` | Database and Redis readiness |

### 3.2 Compounds and units

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| `GET` | `/compounds` | any | Admin sees all |
| `POST` | `/compounds` | admin | Creates compound + default settings |
| `GET` | `/compounds/{id}` | scoped | |
| `PATCH` | `/compounds/{id}` | admin | Name, contact, timezone, settings |
| `DELETE` | `/compounds/{id}` | admin | Fails when dependent rows exist |
| `GET` | `/compounds/{id}/units` | manager | Filters: `status`, `unit_type`, `search` |
| `POST` | `/compounds/{id}/units` | manager | `building`, `unit_number`, `unit_type`, `bedrooms` |
| `GET/PATCH/DELETE` | `/compounds/{id}/units/{unit_id}` | manager | Unit label is derived |

`compound.settings` is a JSON document understood by the decision engine:

```json
{"auto_open_barrier": true, "allow_face_only_entry": true, "gate_webhook_url": null}
```

### 3.3 Gates and cameras

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| `GET` | `/gates` | any scoped | Includes nested camera summaries |
| `POST` | `/gates` | manager | `code` unique per compound |
| `GET/PATCH/DELETE` | `/gates/{id}` | manager (delete: admin) | |
| `POST` | `/gates/{id}/command` | manager | `{action: open\|close\|hold, reason}` → actuator |
| `GET` | `/cameras` | manager | Includes `status`, `last_frame_at`, `last_error` |
| `POST` | `/cameras` | manager | `source_type`: `rtsp`/`usb`/`file`/`demo` |
| `GET/PATCH/DELETE` | `/cameras/{id}` | manager | |
| `POST` | `/cameras/{id}/toggle` | manager | `{is_active}` — enable/disable a stream |

### 3.4 Users (staff accounts)

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| `GET` | `/users` | admin | Filters: `role`, `is_active`, `search` |
| `POST` | `/users` | admin | `compound_id` required for non-admin roles |
| `GET/PATCH` | `/users/{id}` | admin | |
| `DELETE` | `/users/{id}` | admin | Deactivates (never hard-deletes) |
| `POST` | `/users/{id}/reset-password` | admin | `{new_password}` |

### 3.5 Residents and vehicles

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| `GET` | `/residents` | manager | Filters: `unit_id`, `status`, `search` |
| `GET` | `/residents/me` | resident | Own profile + `vehicle_count`, `face_count` |
| `POST` | `/residents` | manager | Optional `user_id` link |
| `GET/PATCH/DELETE` | `/residents/{id}` | manager | Delete fails when vehicles/permits exist |
| `GET` | `/vehicles` | any scoped | Residents always get their own vehicles |
| `POST` | `/vehicles` | manager | Plate normalised, duplicates rejected with 409 |
| `GET/PATCH/DELETE` | `/vehicles/{id}` | manager | `status`: `active`/`suspended`/`inactive` |

Plate handling: the displayed `plate_number` is normalised to `AAA 1234`; the
`plate_normalized` variant (letters + digits only) is used for matching and accepts
Arabic-Indic digits. Lookups also try common OCR confusions (`0/O`, `1/I`, `5/S`).

### 3.6 Visitors and permits

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| `GET` | `/visitors` | any scoped | Filters: `status`, `host_unit_id`, `active_only`, `search` |
| `POST` | `/visitors` | manager or resident | Residents may only invite to their own unit |
| `GET/PATCH/DELETE` | `/visitors/{id}` | scoped | |
| `POST` | `/visitors/{id}/approve` | manager | `pending → approved` |
| `POST` | `/visitors/{id}/reject` | manager | `pending → rejected` |
| `POST` | `/visitors/{id}/check-in` | manager | `approved → checked_in`, sets `actual_arrival` |
| `POST` | `/visitors/{id}/check-out` | manager | `checked_in → checked_out` |
| `POST` | `/visitors/{id}/photo` | manager | Multipart `file` |
| `GET` | `/permits` | any scoped | Filters: `status`, `visitor_id`, `host_unit_id`, `active_only` |
| `POST` | `/permits` | manager or resident | Returns `PMT-YYYYMMDD-XXXXXX` |
| `GET/PATCH/DELETE` | `/permits/{id}` | scoped | Editing windows/limits |
| `POST` | `/permits/{id}/revoke` | manager or host | `{reason}` — terminal state |

Creating a permit for a `pending` visitor auto-approves the visitor. A permit may
carry a `vehicle_plate`; if the plate is not registered yet, GateVision creates a
visitor vehicle so ANPR can match it at the barrier.

```json
{
  "visitor_id": "0d9e…",
  "permit_type": "contractor",
  "start_at": "2026-11-01T06:00:00Z",
  "end_at": "2026-11-01T18:00:00Z",
  "max_entries": 2,
  "vehicle_plate": "GZ 5520",
  "notes": "Elevator maintenance"
}
```

### 3.7 Blacklist and faces

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| `GET` | `/blacklist` | manager | Filters: `entry_type`, `is_active` (omit = all), `search` |
| `POST` | `/blacklist` | manager | `entry_type`: `plate`/`person`/`face` |
| `GET/PATCH/DELETE` | `/blacklist/{id}` | manager | `PATCH {is_active:false}` deactivates |
| `GET` | `/faces` | any scoped | Residents only receive their own embeddings |
| `GET` | `/faces/gallery` | any scoped | `total_embeddings`, `active_embeddings`, `enrolled_residents` |
| `POST` | `/faces/enroll` | manager or self | Multipart `resident_id`, `file`, `overwrite` |
| `POST` | `/faces/{id}/deactivate` | manager | Keeps the row for audit |
| `DELETE` | `/faces/{id}` | manager | Hard delete (GDPR erasure) |

Blacklist payload:

```json
{
  "compound_id": "a2bb…",
  "entry_type": "plate",
  "plate_number": "SUZ 7788",
  "reason": "trespassing",
  "description": "Case SEC-2026-118",
  "expires_at": null
}
```

Face entries may reference `resident_id` or `visitor_id`; the embedding is resolved
automatically when the subject has an enrolled face. Raw vectors are never returned
by the API.

### 3.8 Access logs and detections

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| `GET` | `/access-logs` | any scoped | Residents see only their own records |
| `GET` | `/access-logs/{id}` | scoped | Full snapshot links |
| `POST` | `/access-logs/{id}/override` | manager | `{decision, reason, open_gate, notes}` |
| `POST` | `/access-logs/manual` | manager | Officer-only gate operation |
| `GET` | `/access-logs/export?format=csv\|xlsx` | any scoped | Streams a file |
| `GET` | `/detections` | manager | Raw model output, filters `event_type`, `plate`, `decision` |
| `GET` | `/detections/{id}` | manager | |

`/access-logs` filters: `gate_id`, `decision`, `direction`, `method`, `plate`,
`search`, `resident_id`, `visitor_id`, `vehicle_id`, `start`, `end`, `overridden`,
`requires_review`.

Export: same filters plus `format`; CSV is UTF-8 with BOM (Excel-friendly), XLSX is a
real workbook. Files are named `gatevision-access-logs-<timestamp>.<ext>` and capped
at `EXPORT_ROW_LIMIT` rows.

```bash
curl -s "http://localhost:8000/api/v1/access-logs/export?format=xlsx&decision=deny" \
  -H "Authorization: Bearer $TOKEN" -o denied.xlsx
```

Override example:

```json
{"decision": "allow", "reason": "Identity confirmed by phone", "open_gate": true, "notes": "Guest of unit A-12"}
```

### 3.9 Analytics

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/analytics/dashboard?days=7` | Everything the dashboard needs in one call |
| `GET` | `/analytics/overview` | Headline KPIs for today |
| `GET` | `/analytics/trend?days=7` | Daily `allowed/denied/unknown/review/total` |
| `GET` | `/analytics/occupancy` | Vehicles/residents/persons inside now |
| `GET` | `/analytics/blacklist-breakdown` | Active entries by type |

`/analytics/dashboard` returns `overview`, `trend`, `decision_breakdown`,
`method_breakdown`, `peak_hours` (24 buckets, sparse if no traffic),
`gate_performance`, `recent_access`, `recent_detections` and a 7×24 `heatmap`.

### 3.10 Computer vision

| Method | Path | Roles | Notes |
| --- | --- | --- | --- |
| `GET` | `/cv/status` | any | Active engines, readiness, warnings, gallery size |
| `POST` | `/cv/warmup` | manager | Loads models eagerly |
| `GET` | `/cv/gallery` | any scoped | Gallery statistics |
| `POST` | `/cv/refresh-gallery` | manager | Hot reload after bulk import |
| `GET` | `/cv/workers` | any | In-process worker status |
| `GET` | `/cv/camera-health` | any | Counts by camera status |
| `POST` | `/cv/analyze` | manager | Multipart `gate_id`, `file`, optional `demo_scenario` |
| `POST` | `/cv/analysis/{log_id}/confirm` | manager | Acknowledge a review decision |

`/cv/analyze` runs the full pipeline on an uploaded frame and **persists** the
detection, the access log and the barrier command, exactly like a live camera frame.
In `CV_MODE=mock` an optional scripted scenario can be replayed:

`resident-entry`, `visitor-permit`, `unknown-vehicle`, `blacklisted-plate`,
`resident-pedestrian`, `blocked-person`, `known-face-unknown-car`,
`suspended-resident`.

```bash
curl -s -X POST http://localhost:8000/api/v1/cv/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -F gate_id=$GATE_ID -F demo_scenario=resident-entry \
  -F file=@frame.jpg | jq
```

---

## 4. WebSocket stream

```
ws(s)://<host>/api/v1/ws/events?token=<access token>[&gate_id=<uuid>]
```

* The token is passed as a query parameter because browsers cannot set headers on
  WebSocket handshakes.
* Non-admin users are pinned to their compound; admins may add `compound_id`.
* The server sends a heartbeat comment every 25 s and closes with code `1008` on
  authentication/scope failures.

Event envelope:

```json
{
  "id": "b0f2…",
  "type": "detection.created",
  "occurred_at": "2026-10-31T22:27:38.497702Z",
  "payload": {
    "access_log_id": "e868…",
    "gate_id": "4ccf…",
    "gate_name": "Main Entrance",
    "decision": "allow",
    "reason": "Resident identified by face recognition",
    "plate_number": null,
    "face_similarity": 1.0,
    "snapshot_url": "/media/snapshots/2026/10/31/222738_f59e.jpg",
    "gate_opened": true
  }
}
```

| `type` | Payload highlights |
| --- | --- |
| `detection.created` | decision, reason, plate, visitor, permit, snapshots, processing time |
| `access.decision` | `access_log_id`, `reason_code`, `requires_review`, `gate_opened` |
| `access.override` | officer, new decision, reason |
| `gate.command` | gate code, action (`open`/`close`/`hold`), actor |
| `camera.status` | camera id, status, error, fps |
| `gallery.updated` | requested by/at |
| `maintenance.completed` | counters from the retention job |

Minimal browser client:

```ts
const socket = new WebSocket(
  `wss://gate.example.com/api/v1/ws/events?token=${accessToken}`,
);
socket.onmessage = (event) => {
  const message = JSON.parse(event.data) as { type: string; payload: unknown };
  if (message.type === "detection.created") console.log(message.payload);
};
```

---

## 5. Rate limits and size limits

* Login: `MAX_LOGIN_ATTEMPTS` (default 5) per email per 15 minutes.
* Uploads: `MAX_UPLOAD_MB` (default 10 MB) for face enrollment and image analysis.
* Exports: `EXPORT_ROW_LIMIT` (default 50 000) rows per request.
* List pages: `page_size ≤ 200`.
