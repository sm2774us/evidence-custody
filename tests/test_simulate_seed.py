"""The seed command must populate a live server with usable, verifiable sample data."""

from pathlib import Path
from typing import cast

import httpx
from fastapi.testclient import TestClient

from custody.app import create_app
from custody.auth import Role, issue_token
from custody.config import Settings
from custody.simulate import run_seed


def test_seed_creates_evidence_quarantine_alert_and_gap(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path).with_dev_secrets()
    app = create_app(s)
    http = cast(httpx.Client, TestClient(app))
    lines: list[str] = []
    out = run_seed(http, s.token_secret, device_id="cam-seed", say=lines.append)
    assert out["evidence_id"].startswith("ev_") and out["quarantined_upload_id"].startswith("up_")
    tok = issue_token(s.token_secret, "a", Role.AUDITOR, "agency-1", app.state.svc.clock(), 600)
    hdr = {"authorization": f"Bearer {tok}"}
    assert http.post("/v1/audit/verify", headers=hdr).json()["ok"] is True
    ins = http.get(f"/v1/uploads/{out['quarantined_upload_id']}/inspect", headers=hdr).json()
    assert ins["state"] == "quarantined"
    rd = issue_token(s.token_secret, "r", Role.READER, "agency-1", app.state.svc.clock(), 600)
    gaps = http.get(
        "/v1/devices/cam-seed/sequence-gaps", headers={"authorization": f"Bearer {rd}"}
    ).json()
    assert {2, 3} <= set(gaps["missing"])  # tampered upload + skipped recording
    assert any("Sequence gap check" in x for x in lines)
