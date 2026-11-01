"""Application configuration.

Every runtime knob is provided through environment variables (or a ``.env``
file).  The module exposes a cached :func:`get_settings` accessor so that the
configuration is parsed exactly once per process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

Environment = Literal["development", "staging", "production", "test"]
CvMode = Literal["mock", "real"]


class Settings(BaseSettings):
    """Central GateVision settings (12-factor friendly)."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    APP_NAME: str = "GateVision"
    APP_DESCRIPTION: str = "Smart gate management platform with real-time computer vision"
    ENVIRONMENT: Environment = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["text", "json"] = "text"
    DEFAULT_TIMEZONE: str = "Africa/Cairo"

    # ------------------------------------------------------------- security
    SECRET_KEY: str = "change-me-in-production-please-use-a-long-random-value"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PASSWORD_MIN_LENGTH: int = 8
    MAX_LOGIN_ATTEMPTS: int = 5

    # ------------------------------------------------------------- database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BACKEND_DIR / 'gatevision.db'}"
    DATABASE_ECHO: bool = False
    AUTO_CREATE_TABLES: bool = False
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # ---------------------------------------------------------------- redis
    REDIS_ENABLED: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_EVENT_CHANNEL: str = "gatevision:events"
    CACHE_TTL_SECONDS: int = 30

    # ------------------------------------------------------------------ web
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://localhost:3000",
        ]
    )
    TRUSTED_HOSTS: list[str] = Field(default_factory=lambda: ["*"])
    MEDIA_ROOT: Path = BACKEND_DIR / "media"
    MEDIA_URL: str = "/media"
    MAX_UPLOAD_MB: int = 10

    # ------------------------------------------------------------ bootstrap
    SEED_DEMO_DATA: bool = False
    SEED_ADMIN_EMAIL: str = "admin@gatevision.app"
    SEED_ADMIN_PASSWORD: str = "Admin@12345"
    SEED_ADMIN_NAME: str = "GateVision Administrator"
    DEMO_COMPOUND_NAME: str = "Palm Hills Community"
    DEMO_COMPOUND_CODE: str = "PHC"

    # ------------------------------------------------------------------- cv
    CV_ENABLED: bool = True
    CV_RUNNER_ENABLED: bool = True
    CV_MODE: CvMode = "mock"
    CV_PLATE_DETECTOR: str = "yolo"  # yolo | mock
    CV_PLATE_MODEL_PATH: str = "models/plate_yolov8.pt"
    CV_YOLO_IMAGE_SIZE: int = 640
    CV_YOLO_IOU: float = 0.45
    CV_YOLO_DEVICE: str = ""  # "" = auto (CUDA when present), "cpu", "0", "cuda:1"
    CV_YOLO_HALF: bool = False
    CV_OCR_ALLOWLIST: bool = True

    # Deployment-wide barrier defaults. A compound policy always wins; these
    # let ops point every gate at one controller through the environment.
    BARRIER_DRIVER: str = "simulator"  # simulator | webhook | mqtt | gpio
    BARRIER_WEBHOOK_URL: str = ""
    BARRIER_WEBHOOK_SECRET: str = ""
    BARRIER_WEBHOOK_TIMEOUT_SECONDS: float = 3.0
    BARRIER_COMMAND_TIMEOUT_SECONDS: float = 10.0
    CV_OCR_ENGINE: str = "easyocr"  # easyocr | paddleocr | mock
    CV_OCR_LANGUAGES: list[str] = Field(default_factory=lambda: ["en"])
    CV_FACE_ENGINE: str = "insightface"  # insightface | mock
    CV_FACE_MODEL_NAME: str = "buffalo_l"
    CV_FACE_DET_SIZE: int = 640
    CV_FACE_SIMILARITY_THRESHOLD: float = 0.45
    CV_PLATE_CONFIDENCE_THRESHOLD: float = 0.35
    CV_OCR_MIN_CONFIDENCE: float = 0.45
    CV_MIN_PLATE_ASPECT: float = 1.6
    CV_MAX_PLATE_ASPECT: float = 7.0
    CV_MAX_FPS: float = 5.0
    CV_DEDUPE_SECONDS: float = 8.0
    CV_FRAME_WIDTH: int = 1280
    CV_SNAPSHOT_QUALITY: int = 85
    CV_DEMO_CAMERAS: bool = True
    CV_DEMO_INTERVAL_SECONDS: float = 9.0

    # --------------------------------------------------------------- limits
    DEFAULT_PAGE_SIZE: int = 25
    MAX_PAGE_SIZE: int = 200
    EXPORT_ROW_LIMIT: int = 50_000
    RETENTION_DAYS: int = 365

    # ----------------------------------------------------------- schedulers
    MAINTENANCE_ENABLED: bool = True
    MAINTENANCE_INTERVAL_SECONDS: int = 900

    @field_validator("CORS_ORIGINS", "TRUSTED_HOSTS", "CV_OCR_LANGUAGES", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow comma separated values in environment variables."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("MEDIA_ROOT", mode="before")
    @classmethod
    def _resolve_media_root(cls, value: object) -> object:
        if isinstance(value, str):
            path = Path(value)
            return path if path.is_absolute() else (PROJECT_DIR / path).resolve()
        return value

    @field_validator("CV_MODE", mode="before")
    @classmethod
    def _normalise_cv_mode(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"real", "production", "gpu"}:
                return "real"
            if lowered in {"mock", "demo", "simulation"}:
                return "mock"
        return value

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running with production guarantees."""
        return self.ENVIRONMENT == "production"

    @property
    def is_sqlite(self) -> bool:
        """Return ``True`` when the configured database is SQLite."""
        return self.DATABASE_URL.startswith("sqlite")

    def ensure_directories(self) -> None:
        """Create runtime directories that must exist before serving."""
        self.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
        (self.MEDIA_ROOT / "snapshots").mkdir(parents=True, exist_ok=True)
        (self.MEDIA_ROOT / "faces").mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


settings = get_settings()
