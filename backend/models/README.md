# CV model directory

Place the real weights here; the compose `cv-worker` mounts this directory at
`/app/models` (read-only). Everything except this README is git-ignored
(`*.pt`, `*.onnx`, `*.pth`) — **weights are never committed**.

| File | Purpose | Config |
| --- | --- | --- |
| `plate_yolov8.pt` | Egyptian plate detector (YOLOv8m, default) | `CV_PLATE_MODEL_PATH` |
| `plate_egy_v5.onnx` | optional exported YOLOv5/v7 detector | `CV_PLATE_DETECTOR=onnx` |
| InsightFace `buffalo_l` | face detection + 512-d embeddings (auto-downloaded to `~/.insightface`) | `CV_FACE_MODEL_NAME` |

## Get the Egyptian plate detector

```bash
python3 scripts/fetch_plate_model.py                    # -> plate_yolov8.pt (YOLOv8m, 50 MB)
python3 scripts/fetch_plate_model.py --source egy-v8s   # YOLOv8s, 22 MB (weak CPUs)
python3 scripts/fetch_plate_model.py --verify-only      # re-verify what is already here
```

The script downloads from the upstream GitHub repo, checks the pinned sha256 and
prints the size, task and class names. It refuses HTML error pages, non-YOLO
files and checkpoints without a plate-like class, so a broken download can never
be mistaken for a working detector.

| Source | Upstream | Notes |
| --- | --- | --- |
| `egy-v8m` (default) | [Ahmad-ElToraby/EALPR](https://github.com/Ahmad-ElToraby/EALPR) | YOLOv8m, 3,547 Egyptian images, 99.5 % mAP@50, class `License Plate` |
| `egy-v8s` | [Ahmed482-21albadawy/Egyptian-Plate-Detector-V2](https://github.com/Ahmed482-21albadawy/Egyptian-Plate-Detector-V2) | YOLOv8s, ~2× faster on CPU, class `License Plate` |

Using a YOLOv5/v7 checkpoint (e.g. `yolov7_egy_car_plates_detection`)? Export it
to ONNX and set `CV_PLATE_DETECTOR=onnx`:

```bash
yolo export model=car_plate_detector.pt format=onnx opset=12
cp car_plate_detector.onnx backend/models/plate_egy_v5.onnx
```

## What if the weights are missing?

Nothing crashes: `/health/ready`, `/api/v1/cv/status` and `GET
/api/v1/cv/real-mode` report the exact error and the dashboard shows it, while
the API keeps serving. The CV worker simply produces no detections until a valid
model is present — real mode never invents one.

See [`docs/real-deployment.md`](../docs/real-deployment.md) §3 and
[`docs/rtsp-cameras.md`](../docs/rtsp-cameras.md) §2 for the full runbook.
