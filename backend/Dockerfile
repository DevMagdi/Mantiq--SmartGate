# GateVision backend image.
#
#   docker build -t gatevision-api .
#   docker build --build-arg INSTALL_CV=true -t gatevision-cv .
#
# INSTALL_CV=false keeps the image small (API + exports only); the cv-worker
# service is built with INSTALL_CV=true so YOLO / EasyOCR / InsightFace import.
#
# The image is a two-stage build: compilers and ffmpeg live only in the builder
# stage, so the runtime layer ships the Python environment without toolchains.
# It runs as an unprivileged user (uid 10001) and exposes /metrics + /health.
# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.11

# ---------------------------------------------------------------- build stage
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Only build-time dependencies: wheels/compilers. Nothing here reaches runtime
# except the installed site-packages copied below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-cv.txt requirements-ocr-paddle.txt ./

ARG INSTALL_CV=false
RUN pip install --upgrade pip \
    && pip install --prefix=/install -r requirements.txt \
    && if [ "$INSTALL_CV" = "true" ]; then \
         pip install --prefix=/install \
             --extra-index-url https://download.pytorch.org/whl/cpu \
             -r requirements-cv.txt; \
       fi

# ------------------------------------------------------------------ runtime
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="GateVision API" \
      org.opencontainers.image.description="Smart gate management API with ANPR, face recognition and barrier control" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    OPENCV_VIDEOIO_PRIORITY_MSMF=0

WORKDIR /app

# Runtime shared libraries only (opencv-headless/onnxruntime need glib + gomp).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ffmpeg is only needed to decode exotic RTSP streams in the CV image.
ARG INSTALL_CV=false
RUN if [ "$INSTALL_CV" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends ffmpeg \
        && rm -rf /var/lib/apt/lists/*; \
    fi

COPY --from=builder /install /usr/local

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 10001 gatevision \
    && mkdir -p /data/media /app/models \
    && chown -R gatevision:gatevision /app /data

USER gatevision

EXPOSE 8000

# Python-based probe: no curl/wget needed in the runtime image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
