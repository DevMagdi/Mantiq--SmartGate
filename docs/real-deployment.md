# Real deployment runbook (no mock data)

This is the go-live checklist for a **real** GateVision site: real cameras,
real YOLO/OCR/InsightFace inference, real barrier commands and no invented
detections. Use it for the pilot install this week and for every compound that
follows.

```
Production defaults (docker-compose.yml)
  CV_MODE=real              detections only from camera frames
  CV_DEMO_CAMERAS=false     no synthetic demo cameras
  CV_ALLOW_DEMO_SOURCES=false
  SEED_DEMO_DATA=false      no demo residents/vehicles/history
```

`CV_MODE=mock` still exists for offline development and for the scripted demo —
it is never selected automatically.

- [1. Deploy the stack](#1-deploy-the-stack)
- [2. Connect real RTSP cameras](#2-connect-real-rtsp-cameras)
- [3. Load the real models](#3-load-the-real-models)
- [4. Enroll faces and vehicles](#4-enroll-faces-and-vehicles)
- [5. Configure the barrier (webhook first)](#5-configure-the-barrier-webhook-first)
- [6. Verify: health, cameras, detections](#6-verify-health-cameras-detections)
- [7. Hardware for Egyptian compounds](#7-hardware-for-egyptian-compounds)
- [8. Troubleshooting](#8-troubleshooting)
- [9. Go-live checklist](#9-go-live-checklist)

---

## 1. Deploy the stack

```bash
git clone https://github.com/DevMagdi/Mantiq--SmartGate.git
cd Mantiq--SmartGate
cp .env.example .env          # edit the values below
docker compose up --build -d
```

Minimum `.env` for a real site:

| Variable | Example | Notes |
| --- | --- | --- |
| `SECRET_KEY` | 64 random chars | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | strong password | also change `DATABASE_URL` |
| `CORS_ORIGINS` | `https://gates.compound.eg` | never `*` in production |
| `TRUSTED_HOSTS` | `gates.compound.eg,api.internal` | empty = allow all |
| `CV_MODE` | `real` | the default |
| `SEED_DEMO_DATA` | `false` | the default |
| `CV_MODELS_DIR` | `./backend/models` | mounted read-only at `/app/models` |
| `CAMERAS_JSON` | see step 2 | optional: cameras from the environment |

With `SEED_DEMO_DATA=false` the API creates **only a bootstrap admin** — enough
to log in and build the site from scratch:

```
SEED_ADMIN_EMAIL=admin@gatevision.app      # change before the first boot
SEED_ADMIN_PASSWORD=Admin@12345            # change it after the first login
```

Then, in the dashboard:

1. **Settings → Compound** → *Create compound* (name + code, e.g. `PALM-HILLS`).
2. **Settings → Gates** → add `GATE-IN` (entry) and `GATE-OUT` (exit).
3. **Settings → Cameras** → add the RTSP URLs (step 2 below).

The bootstrap account is only created when the `users` table is empty, so
restarting never overwrites a changed password. In `ENVIRONMENT=production` a
default admin password is reported as a configuration warning at boot.

Services and what they do:

| Service | Role | Restart |
| --- | --- | --- |
| `api` | FastAPI, dashboard API, WebSocket bus, maintenance tasks | `unless-stopped` |
| `cv-worker` | `python -m app.cv.runner`: one thread per camera, YOLO + OCR + InsightFace | healthcheck = heartbeat file |
| `dashboard` | Vite build served by nginx, proxies `/api` | — |
| `postgres` | audit trail (access logs, detections, embeddings) | healthcheck `pg_isready` |
| `redis` | event bus for multi-process deployments | healthcheck `redis-cli ping` |

The API process itself does **not** open cameras when `CV_RUNNER_ENABLED=false`
(compose default); the dedicated `cv-worker` container owns the streams so
restarting the API never interrupts detection.

---

## 2. Connect real RTSP cameras

Two equivalent ways — the dashboard is recommended because it validates the
stream before saving.

### 2a. Dashboard (recommended)

1. **Settings → Cameras → Add camera**.
2. Fill in:
   - **Gate**: the lane this camera watches (`GATE-IN` entry, `GATE-OUT` exit).
   - **Source type**: `rtsp` for IP cameras, `usb` for a local webcam.
   - **Source URL**: `rtsp://user:password@172.16.10.11:554/Streaming/Channels/101`.
   - **FPS limit**: `5` for ANPR (higher does not improve accuracy, only CPU load).
3. Press **Test** on the row — the probe opens the stream, grabs
   `CV_CAMERA_PROBE_FRAMES` frames and reports latency, resolution, brightness
   and a preview JPEG, or an actionable hint (401 → credentials, timeout → VLAN,
   index → USB device).
4. Press **Enable** and confirm the row turns **Online** in under ~10 s.

Common URL patterns:

| Brand | Main stream |
| --- | --- |
| Hikvision / HiLook | `rtsp://admin:pass@IP:554/Streaming/Channels/101` |
| Dahua / Imou | `rtsp://admin:pass@IP:554/cam/realmonitor?channel=1&subtype=0` |
| Uniview | `rtsp://admin:pass@IP:554/media/video1` |
| Axis | `rtsp://root:pass@IP:554/axis-media/media.amp` |
| Generic ONVIF | discover with `ONVIF Device Manager`, copy the RTSP URL it reports |

Use the **substream** (1280×720 / 2 Mbit/s) for detection when the NVR main
stream is 4K — `CV_FRAME_WIDTH` downscales anyway, so decoding a 4K stream only
wastes CPU.

### 2b. Environment (`CAMERAS_JSON`)

Idempotent bootstrap applied on every boot — good for imaging several boxes:

```bash
CAMERAS_JSON='[
  {"gate_code":"GATE-IN","name":"Entry lane","url":"rtsp://admin:${CAM_IN_PASS}@10.0.0.11:554/Streaming/Channels/101","fps_limit":5},
  {"gate_code":"GATE-OUT","name":"Exit lane","url":"rtsp://admin:${CAM_OUT_PASS}@10.0.0.12:554/Streaming/Channels/101"}
]'
CAM_IN_PASS=... CAM_OUT_PASS=...      # ${VAR} is expanded, never stored in the DB
```

`${VAR}` placeholders are expanded at runtime and API responses show the URL
**redacted** (`rtsp://admin:***@10.0.0.11:...`), so passwords never appear in the
dashboard, logs or database backups.

### Transport settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `CV_RTSP_TRANSPORT` | `tcp` | UDP drops packets and breaks OCR — keep `tcp` |
| `CV_RTSP_OPEN_TIMEOUT_MS` | `5000` | socket connect timeout |
| `CV_RTSP_READ_TIMEOUT_MS` | `5000` | per-frame read timeout |
| `CV_RECONNECT_DELAY_SECONDS` | `2` | first retry delay (doubles) |
| `CV_RECONNECT_MAX_DELAY_SECONDS` | `30` | retry ceiling |
| `CV_STALL_TIMEOUT_SECONDS` | `20` | a silent-but-open socket is reopened |

A dead stream is retried forever with backoff; a camera that boots after the
container simply goes online when it appears. Every reconnect is counted and
shown as `reconnects` in `GET /api/v1/cv/camera-health`.

---

## 3. Load the real models

1. Put the plate detector in `backend/models/plate_yolov8.pt`
   (or any path inside the mounted `CV_MODELS_DIR`).
2. Point the config at it (`CV_PLATE_MODEL_PATH`, default `/app/models/plate_yolov8.pt`).
3. InsightFace `buffalo_l` downloads itself on first start into the model cache
   (mount a volume on `~/.insightface` in fully offline sites).

The model must be a YOLOv8/YOLO11 detector with a class named `plate`
(or override `CV_PLATE_CLASS_NAMES`, default
`plate,license_plate,number_plate,plate_number`). Training recipe, export and validation live in
[`cv-pipeline.md`](cv-pipeline.md); Egyptian plate character rules (Arabic →
Latin transliteration, Arabic-Indic digits) are applied after OCR by
`app/cv/plate_rules.py`.

`GET /api/v1/cv/real-mode` lists the exact model path and whether the engine is
ready — the dashboard shows the same panel under **Settings → Cameras**.

### OCR languages

| `CV_OCR_LANGUAGES` | Use |
| --- | --- |
| `["en"]` | Latin plates only — fastest, lowest RAM |
| `["ar","en"]` | mixed Arabic/Latin plates — ~1.6× slower per plate |

`CV_PLATE_CONFIDENCE_THRESHOLD` (detector) and `CV_OCR_MIN_CONFIDENCE` (text)
gate what reaches the decision engine; per-compound overrides live in the
compound `vision` policy (`Settings → Compound → Vision`).

---

## 4. Enroll faces and vehicles

1. **Faces → Enroll**: upload a passport-style photo taken in daylight, face
   filling ~40 % of the frame. The pre-flight quality gate rejects blur, tiny
   faces, extreme angles and duplicates before anything is stored, and returns a
   score plus a fix hint (see [`face-enrollment.md`](face-enrollment.md)).
2. Aim for **2–3 photos per resident** (front + slight angles); the gallery
   keeps the highest-quality embeddings.
3. **Vehicles**: register plate + owner unit + type. The plate is normalised at
   registration, so `أ ب ج ١٢٣٤`, `ABC 1234` and `ABG1234` all match.
4. **Blacklist**: plates, faces and persons — checked *before* any allow rule.

Enrollment is only meaningful with real embeddings: with
`CV_FACE_ENGINE=insightface` the stored vector is a 512-d ArcFace embedding;
a `mock` face engine stores placeholders and is refused in real mode.

---

## 5. Configure the barrier (webhook first)

Per compound: **Settings → Compound → Barrier**. `BARRIER_DRIVER` is only the
fallback for compounds without a policy; the dashboard always wins.

### Webhook (recommended)

```json
{
  "driver": "webhook",
  "webhook": {
    "url": "http://172.16.10.50/relay/open",
    "secret": "shared-secret",
    "timeout_seconds": 3,
    "retries": 2,
    "verify_tls": true
  }
}
```

Every command is a signed POST:

```
POST /relay/open
Content-Type: application/json
X-GateVision-Timestamp: 1793529632
X-GateVision-Signature: sha256=6f1c...
X-GateVision-Event-Id: 0c9f...
X-GateVision-Action: open

{"event_id":"0c9f...","gate":"GATE-IN","action":"open",
 "reason":"Registered resident vehicle (allow)",
 "issued_at":"2026-11-01T10:40:43+00:00","source":"gatevision"}
```

Signature = `HMAC-SHA256(secret, f"{timestamp}.{raw_body}")`. Reject requests
older than ~60 s and never accept a body you did not verify. Minimal verifier:

```python
import hmac, hashlib, time
from flask import Flask, request

app = Flask(__name__)
SECRET = b"shared-secret"

@app.post("/relay/open")
def open_relay():
    ts = request.headers["X-GateVision-Timestamp"]
    if abs(time.time() - int(ts)) > 60:
        return "stale", 400
    expected = "sha256=" + hmac.new(
        SECRET, f"{ts}.".encode() + request.get_data(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, request.headers["X-GateVision-Signature"]):
        return "bad signature", 401
    # pulse the relay … then
    return {"ok": True}, 200
```

A `2xx` response means *the barrier accepted the command*; `4xx` fails
immediately, `429`/`5xx` and transport errors are retried with exponential
backoff. Every attempt is journaled with latency, attempt count and status code.

### MQTT

`BARRIER_DRIVER=mqtt` + broker host/port/topic/QoS/TLS/credentials in the
compound policy. Use QoS 1 and TLS for anything outside the LAN.

### GPIO (optional)

`BARRIER_DRIVER=gpio` — pins, active level and pulse length come from the
policy; the worker host needs `libgpiod` and permission on `/dev/gpiochip*`.

### Decision policy that matters at the gate

`Settings → Compound → Access`:

| Setting | Production value | Why |
| --- | --- | --- |
| `auto_open_barrier` | `true` | the barrier follows the real decision automatically |
| `unknown_vehicle_decision` | `review` | an unregistered plate queues an officer instead of disappearing (`unknown` only logs it) |
| `require_face_for_vehicle` | `false` unless you have a driver-facing camera | otherwise every car falls back to review |
| `allow_blacklist_exit` | `true` | a blacklisted car must be allowed to *leave* |
| `exit_grace_minutes` | `30` | short re-entry after leaving is not counted as a new visit |

### Manual test

**Live Monitor → Barrier control → Test**: sends `open`/`close` through the
*configured real driver* and shows the driver, latency and the controller's
response. Use it before the demo — never a simulator shortcut.

Simulated barriers exist for testing only and are labelled as such in the UI.

---

## 6. Verify: health, cameras, detections

```bash
curl -s localhost:8000/api/v1/health/ready | jq .            # api + db + redis + cameras + cv worker
curl -s localhost:8000/api/v1/cv/real-mode -H "Authorization: Bearer $TOKEN" | jq .
curl -s localhost:8000/api/v1/cv/camera-health -H "Authorization: Bearer $TOKEN" | jq .
```

`/cv/real-mode` is the "no mock data" proof:

```json
{
  "mode": "real",
  "real_detections_only": true,
  "engine_ready": true,
  "cameras_total": 3,
  "cameras_online": 3,
  "demo_cameras": 0,
  "barrier_driver": "webhook",
  "warnings": []
}
```

`real_detections_only` is `true` only when the engine runs in `real` mode **and**
no demo camera exists. If it is false, the Live Monitor shows a yellow banner —
that deployment still shows simulated detections.

Prometheus metrics at `/metrics` (scrape every 15–30 s):
`gatevision_access_decisions_total{decision,reason}`,
`gatevision_barrier_commands_total{driver,action,accepted}`,
`gatevision_vision_results_total{result}`,
`gatevision_cv_mode_real`, `gatevision_cv_engine_ready`,
`gatevision_face_gallery_entries`, `gatevision_barrier_driver`,
`gatevision_http_requests_total{method,path,status}` and
`gatevision_http_request_duration_seconds`.

Detection row fields (also in the dashboard): plate text + confidence, face
similarity, crops (`plate_snapshot_url`, `face_snapshot_url`), `occurred_at`,
`processing_ms`, engine name, decision + reason code and the full decision
details dict for audit.

---

## 7. Hardware for Egyptian compounds

Sizing for **2 lanes / 2 cameras, 1080p substream at 5 fps**:

| Tier | CPU | RAM | Storage | GPU | Handles |
| --- | --- | --- | --- | --- | --- |
| Minimum (pilot) | 4 vCPU (i5-10400 class) | 8 GB | 128 GB SSD | — | 2 lanes, ~4 detections/s, 15–25 FPS OCR budget |
| Recommended | 8 vCPU (i7-12700 / Xeon E-2336) | 16 GB | 480 GB SSD | — | 4–6 lanes |
| With GPU | 6 vCPU (Ryzen 5) | 16 GB | 480 GB SSD | GTX 1660 / RTX 3050 (6 GB) | 8–12 lanes, `CV_YOLO_DEVICE=0`, `CV_YOLO_HALF=true` |
| Edge box | mini-PC i5, fanless, UPS | 16 GB | 240 GB SSD | — | one gate, single compound |

Practical notes for Egyptian sites (heat, dust, brownouts, poor upstream):

- **Instability**: put the PC + NVR on a **UPS (≥ 1000 VA)**; power dips are the
  number one cause of "the gate stopped working".
- **Heat**: a fanless mini-PC in a ventilated cabinet beats a cheap tower in a
  closed guard room in July; keep ambient below 40 °C.
- **Network**: dedicated VLAN for cameras, PoE switch with 2 spare ports,
  cameras on **DHCP reservations**. Do not route camera traffic over the
  compound's shared internet link.
- **Camera choice**: 4 MP (2688×1520) bullet with IR ≥ 30 m and WDR **on**; a
  varifocal lens (2.8–12 mm) beats a fixed 2.8 mm for a 3.5 m lane.
- **Illumination**: a 20 W LED over the plate kills headlight glare and lifts
  OCR accuracy at night more than any model change.
- **Plates**: Egyptian plates are 2-line (private) and 1-line (commercial/taxi);
  mount the camera slightly above plate height, 2–5 m away, angled < 25°.
- **Fallback**: keep a UPS-powered 4G router — the gate must keep working (and
  logging) while the ISP is down. Detection needs no internet.

---

## 8. Troubleshooting

### Camera shows **offline / error** in the dashboard

```bash
docker compose logs -f cv-worker | grep -i "camera"
curl -s -X POST localhost:8000/api/v1/cv/cameras/<id>/test -H "Authorization: Bearer $TOKEN" | jq .
```

| Symptom | Cause | Fix |
| --- | --- | --- |
| Test: `401 Unauthorized` | wrong RTSP password, or RTSP disabled | reset the camera's RTSP/ONVIF user, enable RTSP |
| Test: `timed out` | VLAN/isolation/firewall, wrong IP | `ping` from the worker host, open TCP 554 |
| Test: `Connection refused` | port ≠ 554 or HTTP-only camera | try `:80/...`, check the vendor's RTSP path |
| Test OK, but no detections | camera aimed away, plate too small | re-aim; plate ≥ 100 px wide; check `brightness` in the probe |
| Camera flaps every ~20 s | stream stalls (weak PoE/Wi-Fi) | wire the camera, `CV_STALL_TIMEOUT_SECONDS` up to 30, TCP transport |
| `demo cameras are refused in real mode` | a demo camera survived the switch | delete it or set `CV_ALLOW_DEMO_SOURCES=true` for a staged demo |

### Camera lag / high latency

- Run the CV worker **on the same LAN** as the cameras (never over VPN).
- Use the 720p substream, `CV_MAX_FPS=3–5`; detection does not need 25 fps.
- `CV_FRAME_WIDTH=960` if the CPU is saturated (`docker stats cv-worker`).
- One worker thread per camera: 2 lanes on a 4-vCPU box is the sweet spot.

### Low plate confidence / wrong characters

- Check the crop in the detection detail — if the plate is tiny or blurred, the
  problem is optics, not the model.
- `CV_OCR_ALLOWLIST=true` constrains characters to the Egyptian plate alphabet.
- Add `ar` to `CV_OCR_LANGUAGES` for Arabic-only plates.
- Re-train or fine-tune with 300–500 local plates; see `cv-pipeline.md`.
- Raise `CV_PLATE_CONFIDENCE_THRESHOLD` to `0.45` to send shaky reads to
  **review** instead of guessing (the decision engine answers `review`, never
  `allow`, on low confidence).

### Night vision

- IR illuminators must reach the plate; the probe's `brightness` should be
  > 60. Below 40 the plate is noise.
- Keep `CV_LOW_LIGHT_ENHANCE=true` (CLAHE) — it lifts night crops without
  blowing out headlights.
- Disable the camera's "smart IR" auto-exposure if plates wash out; set a fixed
  shutter (1/250) and WDR to mid.

### Faces not matching

- Re-enroll with the quality gate green (score ≥ 0.6); `CV_FACE_SIMILARITY_THRESHOLD`
  `0.45` is the default — lower it to `0.40` only after checking false matches
  on the blacklist.
- The face camera must be 1.5–2.5 m from the driver, not above the roof line.
- Sunglasses, masks and strong backlight are *expected* failures → the decision
  falls to plate-only rules, which is why vehicles must be registered.

### Barrier does not open

1. **Live Monitor → Test** → does the driver respond?
2. `webhook`: check `docker compose logs api | grep "Barrier command"` for the
   HTTP status; a `4xx` is a controller-side rejection (wrong path, relay
   interlock), `5xx`/timeout is a network/controller problem.
3. `mqtt`: `mosquitto_sub -h <broker> -t '<topic>' -v` while pressing Test.
4. `gpio`: `gpioinfo` / permissions.
5. Verify the decision itself was `allow` — a `review` or `deny` deliberately
   sends no command.

### "Vision engine is not ready"

```bash
docker compose logs cv-worker | grep -iE "model|warm|error"
```

- Missing weights → mount `CV_MODELS_DIR` and set `CV_PLATE_MODEL_PATH`.
- Wrong class name in a custom model → `CV_PLATE_CLASS_NAMES=plate` (multi-class
  models only send the listed classes to OCR).
- Out of memory → reduce `CV_FRAME_WIDTH`, disable the `ar` OCR language.

---

## 9. Go-live checklist

```
[ ] .env: SECRET_KEY, POSTGRES_PASSWORD, CORS_ORIGINS, TRUSTED_HOSTS set
[ ] CV_MODE=real, SEED_DEMO_DATA=false
[ ] Models present: GET /cv/real-mode → engine_ready=true, warnings=[]
[ ] Every camera: Test green, status Online, resolution 720p+, brightness > 60
[ ] /cv/real-mode → real_detections_only=true, demo_cameras=0
[ ] Residents enrolled (quality gate green) and vehicles registered
[ ] Blacklist loaded (plates + faces)
[ ] Barrier driver = webhook/mqtt/gpio (not simulator) and Test opens the real gate
[ ] A known resident vehicle drives in: allow + gate opens + log row with crop
[ ] An unknown vehicle drives in: deny/review + no command sent
[ ] Kill the camera (unplug): status Error → replug → Online without restarting
[ ] Restart the stack: docker compose down && up -d → everything returns online
[ ] Backups: nightly pg_dump + the media volume
[ ] Admin password changed, second officer account created
```

Related docs: [`rtsp-cameras.md`](rtsp-cameras.md) ·
[`cv-pipeline.md`](cv-pipeline.md) · [`face-enrollment.md`](face-enrollment.md) ·
[`hardware.md`](hardware.md) · [`deployment.md`](deployment.md) ·
[`api.md`](api.md)
