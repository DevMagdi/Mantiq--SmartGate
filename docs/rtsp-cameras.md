# Connecting real RTSP cameras (mock → real)

This is the end-to-end runbook for moving a GateVision installation from the
offline demo (`CV_MODE=mock`) to real cameras and real ANPR/face models.

The same steps apply to an on-premise pilot and to production; the only
difference is who performs them (an integrator vs. your operations team).

---

## 0. Before you start

| Requirement | Why |
| --- | --- |
| Cameras reachable from the **CV worker** host/container | the worker pulls the stream itself |
| A plate camera aimed at the vehicle lane, 2–5 m from the plate, ~20–30° | ANPR accuracy collapses at extreme angles |
| Lighting at night (IR or a 20 W lamp over the plate) | unlit plates read as black rectangles |
| A CPU/GPU budget: 4 vCPU + 8 GB RAM for CPU-only, or one CUDA GPU | YOLO + OCR + InsightFace run per frame |
| The CV model weights (plate detector + InsightFace pack) | see step 2 |

Bandwidth per camera is roughly 1–4 Mbit/s for a 1080p H.264 substream; run
the CV worker in the same network segment as the cameras (never over the
public internet).

---

## 1. Prepare the camera

1. **Fixed IP** (DHCP reservation) — the source URL must not change.
2. **Substream for ANPR**: 1280×720 (or 1920×1080), H.264, 10–15 fps,
   keyframe interval ≤ 2 s (GOP 20–30), CBR. Higher resolution helps small
   plates, but 4K usually costs CPU without improving accuracy.
3. **Exposure**: shutter 1/250–1/500 s at night, WDR on, IR enabled.
4. **A dedicated user** with *read-only* stream permission. Do not reuse the
   admin account — RTSP credentials end up in the database.
5. **Privacy masks** (optional): mask neighbouring balconies/windows if the
   frame captures private areas; GateVision stores snapshots of detections.

Test from the CV worker host before touching GateVision:

```bash
# Is the stream reachable and decodable?
ffprobe -v error -rtsp_transport tcp -select_streams v:0 \
        -show_entries stream=codec_name,width,height,avg_frame_rate \
        -of default=noprint_wrappers=1 "rtsp://viewer:PASS@10.20.0.31:554/Streaming/Channels/101"

# Does OpenCV open it? (what the worker actually does)
python -c "import cv2; c=cv2.VideoCapture('rtsp://viewer:PASS@10.20.0.31:554/Streaming/Channels/101', cv2.CAP_FFMPEG); print(c.isOpened())"
```

Common URL templates:

| Vendor | Main stream | Sub stream |
| --- | --- | --- |
| Hikvision | `rtsp://user:pass@IP:554/Streaming/Channels/101` | `…/102` |
| Dahua | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` | `subtype=1` |
| Axis | `rtsp://user:pass@IP/axis-media/media.amp` | `…?resolution=640x360` |
| Uniview | `rtsp://user:pass@IP:554/media/video1` | `video2` |
| ONVIF generic | `rtsp://user:pass@IP:554/onvif1` | `onvif2` |
| USB webcam (dev) | source type `usb`, URL `0` | — |
| Recorded clip (tests) | source type `file`, URL `/data/samples/entry.mp4` | — |

> Use `?tcp` / `-rtsp_transport tcp` when UDP is blocked. GateVision opens
> streams with OpenCV's FFMPEG backend and reconnects automatically
> (2 s backoff) when the stream drops.

---

## 2. Install the real CV stack and model weights

```bash
cd backend
pip install -r requirements.txt -r requirements-cv.txt   # torch CPU wheels need the extra index (see Dockerfile)
```

Put the weights where the workers can read them:

```
backend/models/
├── plate_yolov8.pt        # CV_PLATE_MODEL_PATH
└── insightface/buffalo_l/ # CV_FACE_MODEL_NAME=buffalo_l (auto-downloaded on first use)
```

**Egyptian plates: use a pretrained detector (recommended).** You do not have to
label anything to get started:

```bash
python3 scripts/fetch_plate_model.py             # YOLOv8m, 50 MB (default)
python3 scripts/fetch_plate_model.py --source egy-v8s   # YOLOv8s, 22 MB, CPU-friendly
```

The fetcher writes `backend/models/plate_yolov8.pt` (the compose mount point),
verifies the sha256 and prints the task plus class names. Both models are
single-class `License Plate` YOLOv8 checkpoints trained on Egyptian data, so
`CV_PLATE_DETECTOR=yolo` works with zero extra configuration.

* `egy-v8m` → [Ahmad-ElToraby/EALPR](https://github.com/Ahmad-ElToraby/EALPR),
  3,547 images, 99.5 % mAP@50 — best for GPU / 8-vCPU workers.
* `egy-v8s` → [Egyptian-Plate-Detector-V2](https://github.com/Ahmed482-21albadawy/Egyptian-Plate-Detector-V2)
  — ~2× faster on weak CPUs, slightly lower recall on small/blurred plates.

**YOLOv5/v7 source** (for example `yolov7_egy_car_plates_detection` or
`moshabann/yolov5-alpr-egypt`)? Export it once and switch the engine — no torch
needed on the worker:

```bash
yolo export model=car_plate_detector.pt format=onnx opset=12      # YOLOv5
python export.py --weights car_plate_detector.pt --include onnx    # YOLOv7
cp car_plate_detector.onnx backend/models/plate_egy_v5.onnx
# then: CV_PLATE_DETECTOR=onnx  CV_PLATE_MODEL_PATH=models/plate_egy_v5.onnx
```

`CV_PLATE_DETECTOR=onnx` (aliases `openvino`, `cv2`) runs the graph through
`cv2.dnn`, decodes both YOLOv5 (`[1,N,5+nc]`) and YOLOv8 (`[1,4+nc,N]`) heads and
filters classes before NMS, so a multi-class model still reports plates.

**Training your own model** (only when the shipped models miss your plate style):

1. Label 500–2000 frames from **your own cameras** (Roboflow, CVAT, Label Studio)
   with one class, `plate`.
2. Fine-tune `yolov8n.pt`: `yolo detect train data=plates.yaml model=yolov8n.pt imgsz=640 epochs=80`.
3. Export/copy `runs/detect/train/weights/best.pt` to `models/plate_yolov8.pt`
   (or point `CV_PLATE_MODEL_PATH` at it).
4. Validate on a held-out set of night/rain/angle frames before rolling out —
   the mock scenarios tell you nothing about real accuracy.

The OCR stage is EasyOCR (`en` covers Latinised Egyptian plates; Arabic glyphs
are transliterated automatically by the plate normaliser). If your plates are
purely Arabic, add `ar` to `CV_OCR_LANGUAGES` and re-run the recognition test
in `docs/cv-pipeline.md` §7.

---

## 3. Configure the environment

```bash
# backend/.env (or the api + cv-worker environment in compose)
CV_ENABLED=true
CV_RUNNER_ENABLED=false      # true only for the in-process single-node setup
CV_MODE=real

CV_PLATE_DETECTOR=yolo          # or: onnx (exported YOLOv5/v7)
CV_PLATE_MODEL_PATH=models/plate_yolov8.pt
CV_PLATE_CLASS_NAMES=plate,license_plate,number_plate,plate_number,car_plate,egy_plate,egyptian_plate,لوحة_سيارة,لوحة
CV_PLATE_CONFIDENCE_THRESHOLD=0.35
CV_OCR_ENGINE=easyocr
CV_OCR_LANGUAGES=["en"]
CV_OCR_MIN_CONFIDENCE=0.45
CV_OCR_ALLOWLIST=true

CV_FACE_ENGINE=insightface
CV_FACE_MODEL_NAME=buffalo_l
CV_FACE_SIMILARITY_THRESHOLD=0.45

CV_MAX_FPS=5
CV_FRAME_WIDTH=1280
CV_DEDUPE_SECONDS=8
```

Then restart the API and the worker. `GET /api/v1/cv/status` must report
`mode: "real"`, `engine_ready: true` and the model names in `models_loaded`;
any `warnings` entry explains what failed to load.

Selecting a single-node vs. split deployment:

| Setup | Configuration |
| --- | --- |
| Single node (pilot) | `CV_RUNNER_ENABLED=true` on the API process; workers live inside the API |
| Production (recommended) | `CV_RUNNER_ENABLED=false` on the API, run `python -m app.cv.runner` as the `cv-worker` service (or several, one per GPU) |
| GPU box | set `CV_YOLO_DEVICE=0` (or `cuda:1`), `CV_YOLO_HALF=true` for YOLO; InsightFace picks CUDA automatically |

---

## 4. Register the cameras

Cameras belong to a **gate** (entry/exit lane) and are compound-scoped. Either use
**Settings → Gates & cameras** in the dashboard, or the API:

```bash
curl -X POST http://localhost:8000/api/v1/cameras \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "gate_id": "'$ENTRY_GATE_ID'",
        "name": "Entry ANPR",
        "source_type": "rtsp",
        "source_url": "rtsp://viewer:S3cret@10.20.0.31:554/Streaming/Channels/102",
        "fps_limit": 5,
        "position": "front",
        "notes": "Hikvision DS-2CD7A26, 720p substream, IR on"
      }'
```

Notes:

* The demo cameras seeded in mock mode use `source_type: demo`; **deactivate**
  them (`PATCH /cameras/{id} {"is_active": false}`) before going live, or they
  keep generating scripted detections.
* `fps_limit` caps how often a frame is processed; 3–5 fps is enough for a
  barrier lane, and it keeps CPU predictable (`CV_MAX_FPS` is the global cap).
* One camera per lane direction is typical; add a second (face) camera at the
  pedestrian lane if you enforce `require_face_for_vehicle`.

The worker reloads cameras every few seconds — no restart needed. Confirm with:

```bash
curl -s localhost:8000/api/v1/cameras | jq '.items[] | {name, status, last_frame_at, last_error}'
curl -s localhost:8000/api/v1/cv/camera-health | jq
curl -s localhost:8000/api/v1/cv/workers | jq '.workers'
```

`status` becomes `online` after the first decoded frame (with `last_frame_at`
updating). `error` stores the decoder message in `last_error`.

---

## 5. Tune the thresholds per compound

Global `CV_*` values are the defaults; each compound can override them from
the dashboard (Settings → Policy & barrier) or via the API, without a restart:

```bash
curl -X PATCH localhost:8000/api/v1/compounds/$COMPOUND_ID/settings \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"vision": {"plate_confidence_threshold": 0.4,
                  "ocr_min_confidence": 0.5,
                  "face_similarity_threshold": 0.48}}'
```

Rules of thumb:

| Symptom | Adjustment |
| --- | --- |
| Plates read but wrong characters | raise `ocr_min_confidence`; check `CV_OCR_ALLOWLIST=true`; improve lighting |
| Missed detections at night | lower `plate_confidence_threshold` to 0.3 and monitor false reads |
| Residents refused despite enrolled faces | lower `face_similarity_threshold` (0.40–0.45) and re-vet with `/faces/quality-check` |
| Strangers accepted | raise the similarity threshold (0.50+) and enable `require_face_for_vehicle` |
| Too many events per minute | raise `CV_DEDUPE_SECONDS` (10–15 s) and/or lower `CV_MAX_FPS` |

Record the baseline before and after every change: the dashboard's *Why the
gates decided* panel and `gatevision_access_decisions_total` are the fastest
feedback loops.

---

## 6. Shadow mode before automating the barrier

For the first week run the pipeline **without** opening barriers:

```jsonc
// PATCH /compounds/{id}/settings
{"access": {"auto_open_barrier": false}}
```

Officers keep operating the gate manually (`POST /access-logs/manual` or the
dashboard buttons) while every camera frame is still analysed, logged and
scored. Compare the decisions against reality:

* allowed-but-should-not: plates learnt as unknown / faces matched wrongly;
* denied-but-should-allow: residents without an embedding, visitors without a
  permit, plates typed differently in the registry.

When false negatives are < ~2 % over a few days, re-enable
`auto_open_barrier: true`.

---

## 7. Go-live checklist

- [ ] `GET /cv/status` → `mode: real`, `engine_ready: true`, no warnings
- [ ] Every camera `online`, `last_frame_at` fresh, no `last_error`
- [ ] Demo cameras deactivated, workers report the expected FPS
- [ ] One real detection per lane visible in **Live monitor** with a snapshot
- [ ] Plate normalisation correct for your plates (Arabic ↔ Latin ↔ digits)
- [ ] At least one enrolment per resident (see `docs/face-enrollment.md`)
- [ ] Barrier driver configured and tested (`docs/hardware.md`)
- [ ] `/metrics` scraped, alerts on `gatevision_cv_engine_ready == 0`
- [ ] Retention and backups verified (`docs/deployment.md`)

---

## 8. Troubleshooting

| Symptom | Diagnosis | Fix |
| --- | --- | --- |
| `engine_ready: false`, warning "model not found" | wrong `CV_PLATE_MODEL_PATH` in the worker container | mount `./backend/models` and use a relative path |
| Camera status `error`, `last_error` mentions 401 | RTSP credentials | recreate the camera with a dedicated read-only user |
| Opens then drops every few seconds | UDP blocked / camera session limit | use the TCP substream, raise the camera's concurrent stream limit |
| Everything reads as "unknown plate" | OCR allowlist/language mismatch | `CV_OCR_LANGUAGES=["en","ar"]`, check `CV_OCR_MIN_CONFIDENCE` |
| Faces never match | enrolment photos too small/blurry, gallery not refreshed | run `/faces/quality-check`, then re-enrol and `POST /cv/refresh-gallery` |
| CPU pegged at 100 % | 1080p main streams at 25 fps on CPU | switch to substreams, lower `fps_limit`, `CV_MAX_FPS`, or add a GPU |
| Duplicate detections for one car | dedupe window too short | raise `CV_DEDUPE_SECONDS` to 10–15 |
| `503 vision_unavailable` on `/cv/analyze` | engine never warmed up | check worker logs, then `POST /cv/warmup` |
