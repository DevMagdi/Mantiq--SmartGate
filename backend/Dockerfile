# GateVision backend image.
#
#   docker build -t gatevision-api .
#   docker build --build-arg INSTALL_CV=true -t gatevision-cv .
#
# INSTALL_CV=false keeps the image small (API + exports only); the cv-worker
# service is built with INSTALL_CV=true so YOLO / EasyOCR / InsightFace import.
# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENCV_VIDEOIO_PRIORITY_MSMF=0 \
    MPLBACKEND=Agg

WORKDIR /app

# libgl/libglib are required by opencv-python-headless at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-cv.txt requirements-ocr-paddle.txt ./

ARG INSTALL_CV=false
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && if [ "$INSTALL_CV" = "true" ]; then \
         pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-cv.txt; \
       fi

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests

RUN useradd --create-home --uid 10001 gatevision \
    && mkdir -p /data/media \
    && chown -R gatevision:gatevision /app /data

USER gatevision

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
