# GateVision CV Pipeline

The computer-vision tier turns camera frames into access decisions. It lives entirely
inside `backend/app/cv/` and has no HTTP dependencies, so it can run inside the API
process for a demo or as an independent `cv-worker` container in production.

```
frame → plate detector → OCR → plate candidates ─┐
                                                 ├→ decision engine → barrier
frame → face detector → embeddings → gallery ────┘
                     ↘ crops + annotated frame → /media
```

---

## 1. Two operating modes

| | `CV_MODE=mock` (default) | `CV_MODE=real` |
| --- | --- | --- |
| Plate detector | `MockPlateDetector` | `YOLOPlateDetector` (Ultralytics YOLOv8/v10) |
| OCR | `MockPlateReader` | `EasyOCRPlateReader` (default) or `PaddleOCRPlateReader` |
| Faces | `MockFaceDetector` | `InsightFaceDetector` (buffalo_l, 512-d) |
| Dependencies | core `requirements.txt` only | `requirements-cv.txt` (torch, ultralytics, easyocr, insightface, onnxruntime) |
| Behaviour | Deterministic, scripted detections driven by `app/cv/demo_data.py` | Real inference on live frames |
| Use | CI, demos, UI development, offline evaluation | Production |

The mode is resolved lazily at model-load time. Nothing imports torch/ultralytics
until `engine.warmup()` is called, so the API starts instantly in mock mode and the
web tier never pays the ML import cost when workers are remote.

If real models are requested but the packages or weights are missing, the engine
falls back to mock detectors and records the reason in `/cv/status.warnings` instead
of crashing. This keeps a misconfigured camera from taking down a gate.

---

## 2. Components

```
app/cv/
├── sources.py        FrameSource: OpenCVFrameSource (RTSP/USB/file), DemoFrameSource
├── pipeline.py       GateVisionPipeline + Deduplicator + frame_to_jpeg
├── detectors/
│   ├── yolo_plate.py         YOLO plate detector (letterbox + NMS)
│   ├── insightface_face.py   InsightFace detector + embedding extractor
│   └── mock.py               deterministic detectors used in mock mode
├── recognizers/
│   ├── easyocr_plate.py      EasyOCR reader (configurable languages)
│   ├── paddle_plate.py       PaddleOCR reader (swappable engine)
│   └── mock.py               scripted OCR
├── gallery.py        FaceGallery: in-memory cosine-similarity index
├── snapshots.py      SnapshotStore: annotated frame, plate crop, face crop
├── gate_controller.py AccessDecisionEngine + GateActuator + GateController
├── engine.py         VisionEngine singleton (thread-safe, lazy models)
├── worker.py         CameraWorker thread + ResultEnvelope
├── manager.py        CameraManager: DB → workers, status persistence, events
├── demo_data.py      Scripted scenarios and mock face catalogue
└── runner.py         `python -m app.cv.runner`
```

### Frame sources

`OpenCVFrameSource` wraps `cv2.VideoCapture` and supports:

* `rtsp://user:pass@host:554/stream` — reconnects with exponential backoff and
  reports a `camera.status=error` event on failure.
* USB indices (`0`, `1`, …).
* Video files (`file:///data/clip.mp4` or a pathspec that exists on disk).

`DemoFrameSource` synthesises a 1280×720 frame, renders a scene per scenario and
attaches metadata (`plate_text`, `plate_confidence`, boxes, face keys) that the mock
detectors read through `set_frame_meta()` before `detect()`. Scenarios rotate every
`CV_DEMO_INTERVAL_SECONDS` (default 9 s).

### Pipeline stages

1. **Plate detection** — up to three boxes above `CV_PLATE_CONFIDENCE_THRESHOLD`.
2. **Aspect gate** — boxes outside `[CV_MIN_PLATE_ASPECT, CV_MAX_PLATE_ASPECT]` are
   rejected (logos, signs, headlights).
3. **OCR** — the best-scoring candidate wins; text is cleaned (Arabic-Indic digits →
   ASCII, separators removed) and validated (`≥3` alphanumerics, at least one digit).
4. **Face detection** — quality gates (minimum size, blur score) drop unusable
   detections before embedding extraction.
5. **Gallery match** — cosine similarity against the compound gallery; the best hit
   above `CV_FACE_SIMILARITY_THRESHOLD` is accepted.
6. **Snapshots** — annotated frame (`/media/snapshots/YYYY/MM/DD/`), plate crop
   (`/media/plates/…`) and face crop (`/media/faces/…`) are written with JPEG quality
   `CV_SNAPSHOT_QUALITY`.
7. **Result** — `VisionResult` carries plate text/confidence, face match, crops,
   warnings and processing time.

### Deduplication

`Deduplicator` keeps a TTL cache keyed by plate (or face resident) per camera. A
vehicle idling at the barrier is logged once per `CV_DEDUPE_SECONDS` (default 8 s),
not once per frame. The cache is per camera, so an exit camera still records the
matching exit event.

### Camera worker

Each active camera row becomes a `CameraWorker` thread:

* reads frames at `min(camera.fps_limit, CV_MAX_FPS)`,
* serialises inference through `VisionEngine`'s lock,
* persists status changes (`online`/`error`/`disabled`) and publishes
  `camera.status`,
* hands `ResultEnvelope` objects to the async result handler, which records the
  detection + access log and publishes `detection.created` / `access.decision`.

`CameraManager` reconciles the database with running workers every
`CV_MANAGER_RECONCILE_SECONDS`, so enabling a camera or adding an RTSP URL in the
dashboard takes effect without a restart.

---

## 3. Face gallery

* Embeddings are 512-d float vectors from InsightFace (`buffalo_l`) or the mock
  generator; stored as JSON in `face_embeddings.embedding`.
* `FaceGallery` is a per-compound in-memory matrix; `similarity = dot(a,b)` after L2
  normalisation (cosine).
* The best match wins; ties and low quality fall through to `review`.
* Enrollment (`POST /faces/enroll`) recomputes the gallery and publishes
  `gallery.updated`; workers hot-reload it without restarting.
* Deactivating an embedding keeps the row for audit; deleting removes the vector
  (biometric erasure).
* Raw vectors are never serialised by the API.
* Multiple samples per resident are supported: enrollment can overwrite (replace) or
  append (the best of the stored vectors is used at match time).

Quality gates: faces smaller than ~2% of the frame, or with a Laplacian blur score
below the configured floor, are ignored. Operators are prompted to enroll frontal,
well-lit photographs (checklist in the dashboard).

---

## 4. Decision engine

`AccessDecisionEngine.decide(session, DecisionContext)` evaluates rules in a fixed
order. Every outcome carries a machine-readable `reason_code`, a human `reason`, the
`access_method` (`plate`, `face`, `combined`, `permit`, `manual`), the inferred
direction and whether the decision needs a human.

| # | Condition | Decision | Reason code |
| --- | --- | --- | --- |
| 1 | Plate / face / person on an active blacklist | `deny` | `blacklist_plate`, `blacklist_face`, `blacklist_person` |
| 2 | Exit gate + vehicle inside (or checked-in visitor) | `allow` | `registered_exit`, `visitor_exit` |
| 3 | Vehicle suspended / inactive | `deny` | `vehicle_suspended`, `vehicle_inactive` |
| 4 | Registered vehicle, owner inactive | `deny` | `resident_inactive` |
| 5 | Registered vehicle, recognised face belongs to another resident | `review` | `vehicle_owner_mismatch` |
| 6 | Registered vehicle, owner active | `allow` | `registered_vehicle_with_face` / `registered_vehicle` |
| 7 | Valid visitor permit (window, entries left, visitor state) | `allow` | `visitor_permit` |
| 8 | Permit expired / revoked / not started / entries exhausted | `deny` | `permit_expired`, `permit_revoked`, `permit_not_started`, `permit_exhausted` |
| 9 | Recognised resident + unknown plate | `review` | `known_face_unknown_vehicle` |
| 10 | Recognised resident on foot (or in a registered car) | `allow` | `face_matched_resident` |
| 11 | Plate not registered, or visitor vehicle with no permit | `unknown` | `unknown_plate`, `visitor_vehicle_without_permit` |
| 12 | No usable signal | `unknown` | `no_detection` |

**Direction inference:** entry gates always record entry; exit gates always record
exit; bidirectional gates record exit when the vehicle is flagged `is_inside`, entry
otherwise.

**Barrier policy:** the actuator fires only on `allow` and only when the compound
setting `auto_open_barrier` is true (default). `allow_face_only_entry=false` turns
face-only pedestrian entries into a manual review while keeping vehicle+face matches
automatic. Blacklist hits never open the barrier.

**Business effects of an allow:** vehicle `is_inside` and `last_seen_at` are updated,
permit `entries_used` is incremented, visitor check-in/out timestamps are maintained,
and the access log records the barrier state.

---

## 5. Thresholds and tuning

| Setting | Default | Effect |
| --- | --- | --- |
| `CV_PLATE_CONFIDENCE_THRESHOLD` | 0.35 | Minimum detector score for a plate box |
| `CV_OCR_MIN_CONFIDENCE` | 0.45 | Minimum OCR confidence to accept text |
| `CV_MIN_PLATE_ASPECT` / `CV_MAX_PLATE_ASPECT` | 1.6 / 7.0 | Geometry filter |
| `CV_FACE_SIMILARITY_THRESHOLD` | 0.45 | Cosine similarity for a positive identity |
| `CV_FACE_DET_SIZE` | 640 | InsightFace detector input size |
| `CV_MAX_FPS` | 5 | Upper bound per camera |
| `CV_DEDUPE_SECONDS` | 8 | Duplicate suppression window |
| `CV_FRAME_WIDTH` | 1280 | Frames are resized before inference |
| `CV_SNAPSHOT_QUALITY` | 85 | JPEG quality for stored crops |
| `CV_YOLO_IMAGE_SIZE` | 640 | Detector input resolution |
| `CV_YOLO_IOU` | 0.45 | NMS IoU for the detector |
| `CV_YOLO_DEVICE` | auto | `cpu`, `0`, `cuda:1` (empty = let Ultralytics choose) |
| `CV_YOLO_HALF` | false | FP16 inference on CUDA |
| `CV_OCR_ALLOWLIST` | true | Constrain EasyOCR to plate characters |

### Per-compound overrides

Every value above can be overridden per compound without a restart:

```bash
curl -X PATCH .../api/v1/compounds/$ID/settings -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"vision": {"face_similarity_threshold": 0.48,
                  "plate_confidence_threshold": 0.4,
                  "max_embeddings_per_resident": 4}}'
```

The camera workers reload the policy every few seconds; the upload endpoint
(`/cv/analyze`) reads it per request. See `docs/api.md` §3.2 for the full document.

Raising the face threshold reduces false accepts (faster entry for known residents but
more `review`s); lowering it increases convenience at the cost of security. Calibrate
against your own enrollment photos — the bundled seed gallery is synthetic.

---

## 6. Media layout

```
/data/media/
├── snapshots/2026/10/31/222738_f59eb0b8.jpg   # annotated full frame
├── plates/2026/10/31/222738_plate.jpg          # cropped plate
└── faces/2026/10/31/222738_face.jpg            # cropped face / enrollment
```

URLs are relative (`/media/...`) and served by the API (`StaticFiles`) or nginx. The
retention job deletes files older than `RETENTION_DAYS` and removes rows whose files
disappeared.

---

## 6b. Egyptian plate normalisation

`app/cv/plate_rules.py` turns raw OCR text into a comparable key:

* Arabic → Latin transliteration (`ب ج ١٢٣٤` → `BG1234`), including
  Arabic-Indic digits (`٠١٢٣٤٥٦٧٨٩`) and the letter forms that OCR confuses
  (`أ/إ/آ` → `A`, `ى` → `Y`, `ة` → `H`).
* Re-ordering: Egyptian plates are printed with the digits before the letters in
  some series and after in others, so the canonical form is always
  *letters + digits*; `4821 ABC` and `ABC 4821` normalise to the same key.
* Governorate codes (`CAI`, `GZ`, `ALX`, …) are recognised and kept as a suffix.
* Confusion-aware variants (`0/O`, `1/I`, `2/Z`, `5/S`, `8/B`, `6/G`, `4/A`) are
  generated for database lookups, capped at 32 keys so a query stays cheap.
* `plate_similarity()` and `best_plate_match()` let the API suggest the closest
  registered plate when a read is ambiguous (used by the review flow).

Validation (`parse_plate`) rejects non-plate strings early, and the decision
engine always queries by variants instead of raw text.

---

## 6c. Enrollment quality gates

`app/cv/quality.py` scores a photo **before** an embedding is stored:
resolution, single-face, face-size ratio, blur (variance of Laplacian), exposure
and duplicate similarity. Rejections return `enrollment_rejected` with a list of
actionable issues (code, message, severity, hint). The same code powers
`POST /faces/quality-check`, so an operator can test a photo without storing
anything. Thresholds come from the compound vision policy
(`face_min_quality`, `face_min_blur`, `face_min_resolution`,
`max_embeddings_per_resident`, `duplicate_similarity_threshold`).

Gallery hygiene: `POST /faces/prune` keeps the best-scoring embeddings per
resident (dry-run by default in the dashboard) and deactivates the rest instead
of deleting rows.

---

## 7. Real-mode checklist

1. Install the CV stack: `pip install -r backend/requirements-cv.txt`
   (Docker: the `cv-worker` image is built with `INSTALL_CV=true`).
2. Fetch the Egyptian plate detector:
   `python3 scripts/fetch_plate_model.py` → `backend/models/plate_yolov8.pt`
   (the compose mount point, `CV_PLATE_MODEL_PATH`). `--source egy-v8s` for the
   22 MB CPU-friendly model. For YOLOv5/v7 weights export to ONNX and set
   `CV_PLATE_DETECTOR=onnx` instead.
3. Set `CV_MODE=real` (already the default), `CV_PLATE_DETECTOR=yolo`,
   `CV_OCR_ENGINE=easyocr`, `CV_FACE_ENGINE=insightface`.
4. Run `POST /api/v1/cv/warmup` and confirm `engine_ready=true`; check
   `/cv/status.warnings`.
5. Register cameras with real RTSP URLs and enable them; watch `camera.status`
   events and `/cv/camera-health`.
6. Enroll at least two photos per resident before relying on face-first entry.
7. Replay `POST /api/v1/cv/analyze` with sample frames to validate thresholds before
   switching a lane to automatic mode.

`python -m app.cv.runner` is the production entry point; the API's in-process manager
is intended for development (`CV_RUNNER_ENABLED=true` with `CV_ENABLED=true`).

---

## 8. Extending the pipeline

* **New plate detector:** implement the `PlateDetector` protocol
  (`detect(image) -> list[Detection]`), export it from
  `app/cv/detectors/__init__.py`, select it with `CV_PLATE_DETECTOR`
  (`yolo` → Ultralytics `.pt`, `onnx` → `cv2.dnn`). Class labels are normalised
  by `app.cv.detectors.yolo_plate.normalise_class_name`, so `License Plate`,
  `license-plate` and `لوحة سيارة` all match `CV_PLATE_CLASS_NAMES`.
* **New OCR:** implement `PlateReader.read(image, bbox) -> PlateReading | None`.
* **New face model:** implement `FaceDetector.detect()` returning `FaceDetection`
  objects with normalised embeddings; the gallery math is model-agnostic.
* **Custom rule:** add a `ReasonCode`, implement the branch in
  `AccessDecisionEngine.decide`, and cover it with a test in
  `backend/tests/test_cv_decisions.py`. Keep all I/O inside the provided session.

---

## 9. Privacy and safety

* Face vectors are personal data. Restrict database access, back up encrypted, and
  use `DELETE /faces/{id}` for erasure requests.
* Snapshots may contain bystanders: retention defaults to 365 days and should be
  lowered where local regulation requires it.
* Blacklist decisions fail closed (deny) and never auto-open the barrier.
* Every automated decision is auditable: raw detection, decision, reason code,
  snapshot, officer overrides and barrier state are all persisted.
