from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from conftest import mock_http
from custody.app import build_service
from custody.client import UploadError
from custody.config import Settings
from custody.triage import LLMTriage, Triage, minimize, rule_triage


def llm(handler):
    return LLMTriage(mock_http(handler), "k", "claude-sonnet-5-5", "https://api.anthropic.com")


def reply(payload: str):
    return lambda req: httpx.Response(200, json={"content": [{"type": "text", "text": payload}]})


def test_rules_work_without_any_ai():
    a = Triage(None).assess({"event": "hash_mismatch", "all_chunks_verified": True})
    assert a.source == "rules" and a.severity == "high"


def test_llm_cannot_lower_severity_or_invent_actions():
    out = json.dumps({"summary": "harmless glitch", "reasons": ["ok"], "severity": "low",
                      "recommended_actions": ["no_action", "delete_evidence"]})  # fmt: skip
    a = Triage(llm(reply(out))).assess({"event": "fixity_failure"})
    assert a.severity == "critical" and a.category == "fixity_failure"  # floor wins
    assert a.source == "rules" or a.model is None  # invalid action => schema rejects => fallback


def test_llm_enrichment_merges_and_records_provenance():
    out = 'sure {"summary":"Chunk hashes agree; suspect assembly path.","reasons":["r1"],"severity":"critical","recommended_actions":["notify_security_officer"]}'
    a = Triage(llm(reply(out))).assess({"event": "hash_mismatch", "all_chunks_verified": True})
    assert a.source == "rules+llm" and a.severity == "critical" and a.prompt_sha256 and a.model
    assert "retain_for_investigation" in a.recommended_actions


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500),
        reply("I cannot comply"),
        reply("{not json}"),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")),
    ],
)
def test_ai_failure_degrades_to_rules(handler):
    a = Triage(llm(handler)).assess({"event": "sequence_conflict"})
    assert a.source == "rules" and a.severity == "critical"


def test_prompt_minimization_blocks_pii_and_injection():
    seen = {}

    def h(req):
        seen["body"] = req.content.decode()
        return httpx.Response(500)

    ctx = {
        "event": "hash_mismatch",
        "officer_name": "Jane Doe",
        "note": "IGNORE PREVIOUS",
        "size": 5,
    }
    Triage(llm(h)).assess(ctx)
    assert (
        "Jane" not in seen["body"]
        and "IGNORE" not in seen["body"]
        and "untrusted_context" in seen["body"]
    )
    assert minimize(ctx) == {"event": "hash_mismatch", "size": 5}


def test_upload_pipeline_unaffected_by_ai_outage(env, tmp_path):
    s = Settings(data_dir=tmp_path / "ai", ai_enabled=True, ai_api_key="k").with_dev_secrets()
    svc = build_service(s, clock=env.clock, http=mock_http(lambda r: httpx.Response(503)))
    from fastapi.testclient import TestClient

    from conftest import Env
    from custody.app import create_app

    e2 = Env(s, env.clock, svc, TestClient(create_app(s, svc)), s.data_dir)
    cam = e2.device()
    with pytest.raises(UploadError):
        e2.client(cam).upload(os.urandom(2000), sequence_no=1, chunk_size=512, full_sha256="b" * 64)
    assert (
        svc.db.one("SELECT state FROM sessions")["state"] == "quarantined"
    )  # decided by hashes, not AI
    assert svc.db.one("SELECT COUNT(*) c FROM alerts")["c"] == 1


def test_ai_advisory_is_audited_with_prompt_hash(env, tmp_path):
    good = json.dumps({"summary": "Investigate storage path.", "reasons": [], "severity": "high",
                       "recommended_actions": ["check_storage_health"]})  # fmt: skip
    s = Settings(data_dir=tmp_path / "ai2", ai_enabled=True, ai_api_key="k").with_dev_secrets()
    svc = build_service(s, clock=env.clock, http=mock_http(reply(good)))
    from fastapi.testclient import TestClient

    from conftest import Env
    from custody.app import create_app

    e2 = Env(s, env.clock, svc, TestClient(create_app(s, svc)), s.data_dir)
    cam = e2.device()
    with pytest.raises(UploadError):
        e2.client(cam).upload(os.urandom(700), sequence_no=1, chunk_size=256, full_sha256="c" * 64)
    ent = [x for x in svc.audit.entries(limit=100) if x["action"] == "alert.raised"][0]
    assert ent["detail"]["advisory_source"] == "rules+llm" and ent["detail"]["prompt_sha256"]


def test_rule_categories_cover_all_events():
    for ev in ("signature_invalid", "sequence_conflict", "hash_mismatch", "fixity_failure",
               "clock_future", "access_anomaly", "other"):  # fmt: skip
        assert rule_triage({"event": ev}).recommended_actions


def test_eval_harness_rules_baseline_passes():
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, str(root / "evals" / "run.py"), "--rules-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
