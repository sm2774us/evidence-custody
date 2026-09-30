"""Runtime configuration, sourced from environment variables (12-factor)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

RETENTION_DAYS = {"standard": 2555, "extended": 9125, "permanent": 36500}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("./data")
    signing_key_hex: str = ""  # Ed25519 seed (32 bytes hex) for receipts, checkpoints, reports
    token_secret: str = ""  # HMAC secret for dev bearer tokens (prod: OIDC/mTLS at the edge)
    max_chunk_bytes: int = 8 * 1024 * 1024
    max_object_bytes: int = 64 * 1024 * 1024 * 1024
    session_ttl_hours: int = 72
    future_skew_ms: int = 5 * 60 * 1000
    download_alert_threshold: int = 25
    download_window_ms: int = 60 * 60 * 1000
    denied_alert_threshold: int = 5
    ai_enabled: bool = False
    ai_model: str = "claude-sonnet-5-5"
    ai_base_url: str = "https://api.anthropic.com"
    ai_api_key: str = field(default="", repr=False)
    ai_timeout_s: float = 8.0
    storage_backend: str = "fs"  # "fs" | "s3"
    s3_bucket: str = ""
    s3_kms_key_id: str = ""
    retention_days: dict[str, int] = field(default_factory=lambda: dict(RETENTION_DAYS))

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ
        key = e.get("CUSTODY_ANTHROPIC_API_KEY", "")
        return cls(
            data_dir=Path(e.get("CUSTODY_DATA_DIR", "./data")),
            signing_key_hex=e.get("CUSTODY_SIGNING_KEY", ""),
            token_secret=e.get("CUSTODY_TOKEN_SECRET", ""),
            max_chunk_bytes=int(e.get("CUSTODY_MAX_CHUNK_BYTES", 8 * 1024 * 1024)),
            session_ttl_hours=int(e.get("CUSTODY_SESSION_TTL_HOURS", 72)),
            ai_enabled=e.get("CUSTODY_AI_ENABLED", "0") == "1" and bool(key),
            ai_model=e.get("CUSTODY_AI_MODEL", "claude-sonnet-5-5"),
            ai_api_key=key,
            storage_backend=e.get("CUSTODY_STORAGE", "fs"),
            s3_bucket=e.get("CUSTODY_S3_BUCKET", ""),
            s3_kms_key_id=e.get("CUSTODY_S3_KMS_KEY_ID", ""),
        )

    def with_dev_secrets(self) -> Settings:
        """Fill missing secrets with ephemeral values. Development/tests only."""
        from dataclasses import replace

        return replace(
            self,
            signing_key_hex=self.signing_key_hex or secrets.token_hex(32),
            token_secret=self.token_secret or secrets.token_hex(32),
        )
