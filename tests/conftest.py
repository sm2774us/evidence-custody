from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from custody.app import build_service, create_app
from custody.auth import Role, issue_token
from custody.client import UploadClient
from custody.config import Settings
from custody.device import DeviceIdentity
from custody.service import EvidenceService


class FakeClock:
    def __init__(self) -> None:
        self.t = int(time.time() * 1000)

    def __call__(self) -> int:
        return self.t

    def advance(self, ms: int) -> None:
        self.t += ms


@dataclass
class Env:
    settings: Settings
    clock: FakeClock
    svc: EvidenceService
    http: TestClient
    root: Path

    def tok(self, sub: str, role: Role | str, agency: str = "agency-1", ttl: int = 3600) -> str:
        return issue_token(self.settings.token_secret, sub, Role(role), agency, self.clock(), ttl)

    def h(self, sub: str, role: Role | str, agency: str = "agency-1") -> dict[str, str]:
        return {"authorization": f"Bearer {self.tok(sub, role, agency)}"}

    def device(self, device_id: str = "cam-0001", agency: str = "agency-1") -> DeviceIdentity:
        cam = DeviceIdentity(device_id, "officer-77", agency)
        r = self.http.post("/v1/devices", headers=self.h("admin-a", "admin", agency), json={
            "device_id": device_id, "public_key": cam.public_hex,
            "officer_id": "officer-77", "agency_id": agency})  # fmt: skip
        assert r.status_code == 201, r.text
        r = self.http.post(
            f"/v1/devices/{device_id}/activate", headers=self.h("admin-b", "admin", agency)
        )
        assert r.status_code == 200, r.text
        return cam

    def client(self, cam: DeviceIdentity, **kw: Any) -> UploadClient:
        return UploadClient(self.http, self.tok(cam.device_id, "device", cam.agency_id), cam,
                            sleep=lambda _: None, **kw)  # fmt: skip

    def stored(
        self, data: bytes | None = None, seq: int = 1, **kw: Any
    ) -> tuple[DeviceIdentity, dict[str, Any]]:
        cam = self.device()
        rec = self.client(cam).upload(
            data or os.urandom(3000), sequence_no=seq, chunk_size=1024, **kw
        )
        return cam, rec


@pytest.fixture
def env(tmp_path: Path) -> Env:
    clock = FakeClock()
    s = Settings(
        data_dir=tmp_path, download_alert_threshold=5, denied_alert_threshold=3
    ).with_dev_secrets()
    svc = build_service(s, clock=clock)
    return Env(s, clock, svc, TestClient(create_app(s, svc)), tmp_path)


def mock_http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))
