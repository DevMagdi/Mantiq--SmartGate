#!/usr/bin/env python3
"""Download and verify an Egyptian license-plate detector for GateVision.

Two community-trained **YOLOv8** models are supported out of the box. Both are
single-class (``License Plate``) detectors trained on Egyptian plates, so they
drop straight into the Ultralytics pipeline used by ``CV_MODE=real``:

===========================  ==========================  =======  ===========
source                       upstream                    size     notes
===========================  ==========================  =======  ===========
``egy-v8m`` (default)        Ahmad-ElToraby/EALPR        50.8 MB  YOLOv8m,
                                                                  99.5 % mAP@50
``egy-v8s``                  Ahmed482-21albadawy/        22.0 MB  YOLOv8s,
                             Egyptian-Plate-Detector-V2            ~2× faster
                                                                  on CPU
===========================  ==========================  =======  ===========

Examples
--------
    python scripts/fetch_plate_model.py --list
    python scripts/fetch_plate_model.py                     # -> backend/models/plate_yolov8.pt
    python scripts/fetch_plate_model.py --source egy-v8s    # lighter CPU model
    python scripts/fetch_plate_model.py --url https://…/best.pt --no-checksum
    python scripts/fetch_plate_model.py --verify-only       # check what is on disk

Only the Python standard library is used, so it runs on a bare host (or inside
the api/cv-worker container) before the CV extras are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickletools
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = REPO_ROOT / "backend" / "models" / "plate_yolov8.pt"

USER_AGENT = "GateVision-model-fetcher/1.0 (+https://github.com/DevMagdi/Mantiq--SmartGate)"


@dataclass(frozen=True)
class ModelSource:
    """One downloadable checkpoint plus the facts needed to verify it."""

    key: str
    title: str
    repo: str
    path: str
    sha256: str
    size: int
    license_note: str
    hardware_note: str


SOURCES: dict[str, ModelSource] = {
    "egy-v8m": ModelSource(
        key="egy-v8m",
        title="YOLOv8m Egyptian license plate detector (best accuracy)",
        repo="Ahmad-ElToraby/EALPR",
        path="models/plate_detector.pt",
        sha256="c7ce27a03aea4e60ee7a9577e904e2d581814108641ec9a30297186e522b8c04",
        size=50_816 * 1024,
        license_note=(
            "Trained by the EALPR/Aman project (Ahmad-ElToraby) and published as MIT in "
            "its README; keep the upstream attribution when you deploy it."
        ),
        hardware_note="8 vCPU or a GPU; ~80-150 ms/frame on a 4-vCPU CPU box at 640px",
    ),
    "egy-v8s": ModelSource(
        key="egy-v8s",
        title="YOLOv8s Egyptian license plate detector (fastest on CPU)",
        repo="Ahmed482-21albadawy/Egyptian-Plate-Detector-V2",
        path="Models/plate_detector.pt",
        sha256="879c47a21d34c89d07f53dc49d90ee461f80d1ee0a866d0178857b3b5e992b43",
        size=21_976 * 1024,
        license_note=(
            "Published by Ahmed482-21albadawy for educational use; no explicit license "
            "file upstream — confirm the terms before commercial redistribution."
        ),
        hardware_note="4 vCPU mini-PC; ~40-80 ms/frame at 640px",
    ),
}

PLATE_CLASS_HINTS = (
    "plate",
    "license",
    "licence",
    "number",
    "لوحة",
)


class FetchError(RuntimeError):
    """Raised when a download cannot be completed or verified."""


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def inspect_checkpoint(path: Path) -> dict[str, object]:
    """Return a small report about a ``.pt`` checkpoint without importing torch.

    Ultralytics checkpoints are ZIP archives (``torch.save`` >= 1.6) that contain
    ``*/data.pkl`` with the model definition. Reading it as a ZIP is enough to
    prove the file is a real YOLO detection model *and* to extract the class
    names, which is exactly what the operator needs to know before a demo.
    """
    report: dict[str, object] = {
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "sha256": sha256_file(path) if path.exists() else "",
        "is_torch_archive": False,
        "is_ultralytics": False,
        "is_detection_model": False,
        "task": None,
        "class_names": [],
        "looks_like_plate_model": False,
        "problem": None,
    }
    if not path.exists():
        report["problem"] = "file does not exist"
        return report
    try:
        with zipfile.ZipFile(path) as archive:
            report["is_torch_archive"] = True
            pickles = [name for name in archive.namelist() if name.endswith("data.pkl")]
            if not pickles:
                report["problem"] = "archive has no data.pkl (not a torch checkpoint)"
                return report
            raw = archive.read(pickles[0])
    except zipfile.BadZipFile:
        report["problem"] = "not a ZIP/torch checkpoint (wrong file or HTML error page)"
        return report

    report["is_ultralytics"] = b"ultralytics" in raw
    report["is_detection_model"] = b"DetectionModel" in raw or b"DetectionTrainer" in raw

    strings = _pickle_strings(raw)
    task = _guess_task(strings)
    report["task"] = task
    report["versions"] = _guess_versions(strings)
    names = [value for value in strings if _looks_like_class_name(value)]
    report["class_names"] = names[:8]
    report["looks_like_plate_model"] = any(
        hint in name.lower() for name in names for hint in PLATE_CLASS_HINTS
    )
    return report


def _pickle_strings(raw: bytes) -> list[str]:
    """Return every string stored in a pickle, without executing it."""
    values: list[str] = []
    try:
        for opcode, argument, _ in pickletools.genops(raw):
            if isinstance(argument, str):
                values.append(argument)
            elif isinstance(argument, bytes):
                try:
                    values.append(argument.decode("utf-8"))
                except UnicodeDecodeError:
                    continue
    except Exception:  # noqa: BLE001 - a checkpoint we cannot parse is still verifiable
        return []
    return values


def _guess_task(strings: list[str]) -> str | None:
    for index, value in enumerate(strings):
        if value == "task" and index + 1 < len(strings):
            candidate = strings[index + 1].strip().lower()
            if candidate in {"detect", "segment", "classify", "pose", "obb"}:
                return candidate
    for value in strings:
        lowered = value.strip().lower()
        if lowered in {"detect", "segment", "classify", "pose", "obb"}:
            return lowered
    return None


def _guess_versions(strings: list[str]) -> list[str]:
    found: list[str] = []
    for value in strings:
        if re.fullmatch(r"\d+\.\d+\.\d+", value.strip()) and value not in found:
            found.append(value.strip())
    return found[:3]


def _looks_like_class_name(value: str) -> bool:
    text = value.strip()
    if not 3 <= len(text) <= 30:
        return False
    if any(marker in text for marker in ("\\", "/", "http", ".pt", ".onnx", ":")):
        return False
    if not re.fullmatch(r"[A-Za-z\u0600-\u06FF][A-Za-z0-9 _\-\u0600-\u06FF]*", text):
        return False
    return any(hint in text.lower() for hint in PLATE_CLASS_HINTS)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, *, expected_sha256: str | None, check_checksum: bool = True) -> dict[str, object]:
    """Verify a downloaded checkpoint, raising :class:`FetchError` on problems."""
    report = inspect_checkpoint(path)
    if report["problem"]:
        raise FetchError(str(report["problem"]))
    if not report["is_torch_archive"]:
        raise FetchError("file is not a torch checkpoint")
    if not report["is_ultralytics"]:
        raise FetchError("checkpoint does not look like an Ultralytics YOLO model")
    if not report["is_detection_model"]:
        raise FetchError("checkpoint does not contain a YOLO DetectionModel")
    if not report["looks_like_plate_model"]:
        raise FetchError(
            "checkpoint has no plate-like class names; this is probably not a plate detector"
        )
    if check_checksum and expected_sha256 and report["sha256"] != expected_sha256:
        raise FetchError(
            f"sha256 mismatch: got {report['sha256']}, expected {expected_sha256}"
        )
    return report


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def source_urls(source: ModelSource, ref: str = "main") -> list[str]:
    """Return candidate download URLs, most direct first."""
    branch = "master" if source.repo.endswith("EALPR") else ref
    return [
        f"https://github.com/{source.repo}/raw/{branch}/{source.path}",
        f"https://raw.githubusercontent.com/{source.repo}/{branch}/{source.path}",
        # GitHub API works in restricted networks (and honours GITHUB_TOKEN).
        f"https://api.github.com/repos/{source.repo}/contents/{source.path}?ref={branch}",
    ]


def _download_url(url: str, destination: Path, *, timeout: float = 60.0) -> None:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github.raw"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed hosts
        if response.status != 200:
            raise FetchError(f"HTTP {response.status} for {url}")
        with destination.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)


def download(source: ModelSource, destination: Path, *, allow_api: bool = True) -> Path:
    """Download a model, trying each URL in turn."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    urls = source_urls(source)
    if not allow_api:
        urls = [url for url in urls if "api.github.com" not in url]
    for url in urls:
        temp = Path(tempfile.mkstemp(suffix=".pt", dir=destination.parent)[1])
        try:
            print(f"→ downloading {source.repo}/{source.path} from {url.split('?')[0]}")
            _download_url(url, temp)
            if temp.stat().st_size < 1024:
                raise FetchError("downloaded file is suspiciously small")
            shutil.move(str(temp), destination)
            print(f"✓ saved {destination} ({destination.stat().st_size / 1048576:.1f} MB)")
            return destination
        except (FetchError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            errors.append(f"{url.split('?')[0]}: {exc}")
            print(f"  … source unavailable ({type(exc).__name__})")
        finally:
            temp.unlink(missing_ok=True)
    raise FetchError("all download sources failed:\n  " + "\n  ".join(errors))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_list() -> None:
    print("Available Egyptian plate models:\n")
    for key, source in SOURCES.items():
        print(f"  {key}{' (default)' if key == 'egy-v8m' else ''}")
        print(f"    {source.title}")
        print(f"    upstream : https://github.com/{source.repo}/{source.path}")
        print(f"    sha256   : {source.sha256}")
        print(f"    hardware : {source.hardware_note}")
        print(f"    license  : {source.license_note}\n")


def _default_destination() -> Path:
    env_path = os.environ.get("CV_PLATE_MODEL_PATH", "").strip()
    if env_path:
        candidate = Path(env_path)
        # Container paths like /app/models/... are mapped back to ./backend/models.
        if candidate.is_absolute() and candidate.parts[:2] == ("/", "app"):
            return REPO_ROOT / "backend" / "models" / candidate.name
        return candidate if candidate.is_absolute() else REPO_ROOT / candidate
    return DEFAULT_DEST


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download + verify an Egyptian license-plate YOLOv8 model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true", help="list the supported models")
    parser.add_argument("--source", default="egy-v8m", choices=sorted(SOURCES), help="model to fetch")
    parser.add_argument("--url", help="download any .pt URL instead of a known source")
    parser.add_argument("--dest", type=Path, help="destination path (default: backend/models/plate_yolov8.pt)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    parser.add_argument("--verify-only", action="store_true", help="only verify the file on disk")
    parser.add_argument("--no-checksum", action="store_true", help="skip the pinned sha256 comparison")
    parser.add_argument("--json", action="store_true", help="print the verification report as JSON")
    args = parser.parse_args(argv)

    if args.list:
        _print_list()
        return 0

    destination = args.dest or _default_destination()

    if args.verify_only:
        try:
            report = verify_file(destination, expected_sha256=None, check_checksum=False)
        except FetchError as exc:
            print(f"✗ {destination}: {exc}", file=sys.stderr)
            return 1
        _emit(report, as_json=args.json)
        return 0

    if destination.exists() and not args.force:
        print(f"! {destination} already exists — verifying it instead of downloading "
              "(use --force to replace)")
        try:
            report = verify_file(destination, expected_sha256=None, check_checksum=False)
        except FetchError as exc:
            print(f"✗ existing file failed verification: {exc}", file=sys.stderr)
            return 1
        _emit(report, as_json=args.json)
        return 0

    if args.url:
        source = ModelSource(
            key="custom",
            title=args.url,
            repo="custom",
            path=args.url,
            sha256="",
            size=0,
            license_note="provided by the operator — verify the upstream terms",
            hardware_note="unknown",
        )
        try:
            _download_url(args.url, destination)
        except Exception as exc:  # noqa: BLE001 - CLI surface
            print(f"✗ download failed: {exc}", file=sys.stderr)
            return 1
        expected = None
    else:
        source = SOURCES[args.source]
        try:
            download(source, destination)
        except FetchError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1
        expected = None if args.no_checksum else source.sha256

    try:
        report = verify_file(destination, expected_sha256=expected, check_checksum=not args.no_checksum)
    except FetchError as exc:
        print(f"✗ verification failed: {exc}", file=sys.stderr)
        return 1

    _emit(report, as_json=args.json)
    print("\nNext steps:")
    print("  1. CV_MODE=real (default) and CV_PLATE_DETECTOR=yolo")
    print(f"  2. CV_PLATE_MODEL_PATH={_container_hint(destination)}")
    print("  3. docker compose up -d && curl -s localhost:8000/api/v1/cv/real-mode")
    return 0


def _container_hint(destination: Path) -> str:
    try:
        return "/app/models/" + destination.relative_to(REPO_ROOT / "backend" / "models").as_posix()
    except ValueError:
        return str(destination)


def _emit(report: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=2))
        return
    print("✓ model verified")
    print(f"  file        : {report['path']}")
    print(f"  size        : {int(report['size']) / 1048576:.1f} MB")
    print(f"  sha256      : {report['sha256']}")
    print(f"  task        : {report['task'] or 'unknown'}")
    print(f"  classes     : {', '.join(report['class_names']) or 'unknown'}")


if __name__ == "__main__":
    raise SystemExit(main())
