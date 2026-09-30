from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custody.cli import main as cli_main
from custody.crypto import Signer, canonical_json
from custody.device import DeviceIdentity
from custody.errors import WormViolation
from custody.storage import FileWormStore, S3WormStore

VECTOR = Path(__file__).parent / "vectors" / "manifest_vector.json"


def test_interop_vector_matches_typescript_sdk():
    """The same vector is asserted by sdk-ts/test - cross-language signature compatibility."""
    v = json.loads(VECTOR.read_text())
    ident = DeviceIdentity("cam-1", "o-1", "a-1", seed_hex=v["seed_hex"])
    assert ident.public_hex == v["public_key_hex"]
    assert canonical_json(v["manifest"]).decode() == v["canonical"]
    assert ident.sign(v["canonical"].encode()) == v["signature"]  # Ed25519 is deterministic


def test_endpoints_health_metrics_keys(env):
    env.stored()
    assert env.http.get("/healthz").json() == {"status": "ok"}
    assert env.http.get("/readyz").status_code == 200
    m = env.http.get("/metrics").text
    assert "custody_evidence_stored_total" in m and "custody_oldest_open_upload_age_seconds" in m
    assert env.http.get("/v1/keys").json()["public_key"] == env.svc.signer.public_hex
    r = env.http.get("/healthz")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-request-id"]


def test_invalid_manifest_and_limits(env):
    cam = env.device()
    h = env.h(cam.device_id, "device")
    r = env.http.post(
        "/v1/uploads", headers=h, json={"manifest": {"bogus": 1}, "signature": "0" * 128}
    )
    assert r.status_code == 422
    r = env.http.put("/v1/uploads/up_nope/chunks/0", headers=h, content=b"x")
    assert r.status_code == 404


def test_worm_key_traversal_blocked(tmp_path):
    st = FileWormStore(tmp_path)
    with pytest.raises(WormViolation):
        st.open_original("../../etc/passwd", "v")
    with pytest.raises(WormViolation):
        st.delete("a/b")


def test_s3_adapter_uses_compliance_lock_and_checksum(tmp_path):
    c = MagicMock()
    c.put_object.return_value = {"VersionId": "vid-1"}
    src = tmp_path / "o"
    src.write_bytes(b"abc")
    st = S3WormStore(c, "bkt", "kms-key")
    until = int(datetime(2033, 1, 1, tzinfo=UTC).timestamp() * 1000)
    assert (
        st.put_original(
            "a/b/ev_1",
            src,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            until,
        )
        == "vid-1"
    )
    kw = c.put_object.call_args.kwargs
    assert kw["ObjectLockMode"] == "COMPLIANCE" and kw["IfNoneMatch"] == "*"
    assert kw["ServerSideEncryption"] == "aws:kms" and kw["ChecksumSHA256"].endswith("=")
    st.set_legal_hold("a/b/ev_1", "vid-1", "lh", True)
    assert c.put_object_legal_hold.call_args.kwargs["LegalHold"] == {"Status": "ON"}
    with pytest.raises(WormViolation):
        st.delete("x")


def test_cli_init_token_and_verify(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CUSTODY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CUSTODY_SIGNING_KEY", Signer("11" * 32).public_hex and "11" * 32)
    monkeypatch.setenv("CUSTODY_TOKEN_SECRET", "s3cret")
    assert cli_main(["init"]) == 0
    assert cli_main(["issue-token", "--sub", "u", "--role", "auditor", "--agency", "a"]) == 0
    assert cli_main(["verify-audit"]) == 0
    assert cli_main(["checkpoint"]) == 0
    assert cli_main(["fixity"]) == 0
    assert cli_main(["expire"]) == 0
    assert cli_main(["scan"]) == 0
    assert "ok" in capsys.readouterr().out


def test_demo_runs():
    from custody.simulate import run_demo

    assert run_demo() == 0


def test_mcp_server_registers_read_only_tools(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    monkeypatch.setenv("CUSTODY_DATA_DIR", str(tmp_path))
    from custody.mcp_server import build_server

    srv = build_server()
    import asyncio

    tools = asyncio.run(srv.list_tools())
    assert {t.name for t in tools} == {
        "open_alerts",
        "verify_audit_chain",
        "upload_status",
        "explain_quarantine",
    }
