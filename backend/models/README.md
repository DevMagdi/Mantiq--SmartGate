# CV model directory

Place the real weights here; the compose `cv-worker` mounts this directory at
`/app/models` (read-only).

| File | Purpose | Config |
| --- | --- | --- |
| `plate_yolov8.pt` | YOLOv8/v10 license-plate detector | `CV_PLATE_MODEL_PATH` |
| InsightFace `buffalo_l` | face detection + 512-d embeddings (auto-downloaded) | `CV_FACE_MODEL_NAME` |

The plate detector is **not** bundled: download or train a model that has a
`plate` class and drop it here. See `docs/real-deployment.md` §3.

Missing weights do not crash the API; `/health/ready`, `/cv/status` and
`GET /cv/real-mode` report the exact error and the dashboard shows it.
