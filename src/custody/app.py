"""Composition root + FastAPI application."""

import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .audit import AuditLog, Ctx
from .auth import Principal, parse_token
from .config import Settings
from .crypto import Signer
from .db import Database
from .errors import AuthError, CustodyError
from .metrics import Metrics
from .models import CreateUpload, DeviceRegistration, Disposition, HoldRequest
from .service import EvidenceService
from .storage import FileWormStore, ObjectStore, S3WormStore, Staging
from .triage import LLMTriage, Triage

log = logging.getLogger("custody")


def build_service(settings: Settings, clock: Callable[[], int] | None = None,
                  http: httpx.Client | None = None,
                  store: ObjectStore | None = None) -> EvidenceService:  # fmt: skip
    clock = clock or (lambda: int(time.time() * 1000))
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(str(settings.data_dir / "custody.db"))
    signer = Signer(settings.signing_key_hex)
    if store is None:
        if settings.storage_backend == "s3":  # pragma: no cover
            import boto3

            store = S3WormStore(boto3.client("s3"), settings.s3_bucket, settings.s3_kms_key_id)
        else:
            store = FileWormStore(settings.data_dir)
    llm = None
    if settings.ai_enabled:
        llm = LLMTriage(http or httpx.Client(), settings.ai_api_key, settings.ai_model,
                        settings.ai_base_url, settings.ai_timeout_s)  # fmt: skip
    return EvidenceService(settings, db, AuditLog(db, signer, clock), store,
                           Staging(settings.data_dir), signer, clock, Metrics(), Triage(llm))  # fmt: skip


def _ctx(request: Request) -> Ctx:
    c: Ctx = request.state.ctx
    return c


def _principal(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    svc: EvidenceService = request.app.state.svc
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("bearer token required")
    p = parse_token(request.app.state.settings.token_secret, authorization[7:], svc.clock())
    if svc.db.one("SELECT 1 FROM revoked_tokens WHERE jti=?", (p.jti,)):
        raise AuthError("token revoked")
    return p


P = Annotated[Principal, Depends(_principal)]
C = Annotated[Ctx, Depends(_ctx)]


def create_app(settings: Settings | None = None, service: EvidenceService | None = None) -> FastAPI:
    settings = (settings or Settings.from_env()).with_dev_secrets()
    svc = service or build_service(settings)
    app = FastAPI(title="Evidence Custody API", version="1.0.0", docs_url="/docs")
    app.state.svc, app.state.settings = svc, settings

    @app.exception_handler(CustodyError)
    async def _err(_: Request, exc: CustodyError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "message": exc.message, **exc.extra}, exc.status)

    @app.middleware("http")
    async def _mw(request: Request, call_next: Callable[..., Any]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.ctx = Ctx(ip=request.client.host if request.client else "-", request_id=rid)
        t0 = time.perf_counter()
        resp: Response = await call_next(request)
        resp.headers.update({"x-request-id": rid, "cache-control": "no-store",
                             "x-content-type-options": "nosniff"})  # fmt: skip
        log.info(json.dumps({"rid": rid, "method": request.method, "path": request.url.path,
                             "status": resp.status_code,
                             "ms": round((time.perf_counter() - t0) * 1000, 1)}))  # fmt: skip
        return resp

    # ---- ops ---------------------------------------------------------------------------
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        chain = svc.audit.verify()
        return JSONResponse({"ready": chain.ok, "audit_entries": chain.entries,
                             "audit_error": chain.error}, 200 if chain.ok else 503)  # fmt: skip

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return svc.metrics.render()

    @app.get("/v1/keys")
    def keys() -> dict[str, str]:
        return {"key_id": svc.signer.key_id, "public_key": svc.signer.public_hex, "alg": "Ed25519"}

    # ---- devices -----------------------------------------------------------------------
    @app.post("/v1/devices", status_code=201)
    def register_device(body: DeviceRegistration, p: P, c: C) -> dict[str, Any]:
        return svc.register_device(p, body.device_id, body.public_key, body.officer_id,
                                   body.agency_id, c)  # fmt: skip

    @app.post("/v1/devices/{device_id}/activate")
    def activate_device(device_id: str, p: P, c: C) -> dict[str, Any]:
        return svc.activate_device(p, device_id, c)

    @app.post("/v1/devices/{device_id}/revoke")
    def revoke_device(device_id: str, p: P, c: C, reason: str = "unspecified") -> dict[str, Any]:
        return svc.revoke_device(p, device_id, reason, c)

    @app.get("/v1/devices/{device_id}/sequence-gaps")
    def gaps(device_id: str, p: P, c: C) -> dict[str, Any]:
        return {"device_id": device_id, "missing": svc.sequence_gaps(p, device_id, c)}

    # ---- upload path -------------------------------------------------------------------
    @app.post("/v1/uploads", status_code=201)
    def create_upload(body: CreateUpload, p: P, c: C) -> dict[str, Any]:
        return svc.create_upload(p, body.manifest, body.signature, c)

    @app.get("/v1/uploads/{sid}")
    def upload_status(sid: str, p: P, c: C) -> dict[str, Any]:
        return svc.upload_status(p, sid, c)

    @app.put("/v1/uploads/{sid}/chunks/{idx}")
    async def put_chunk(sid: str, idx: int, request: Request, p: P, c: C) -> dict[str, Any]:
        cl = request.headers.get("content-length")
        if cl and int(cl) > settings.max_chunk_bytes:
            raise CustodyError("chunk too large")
        data = await request.body()
        return await run_in_threadpool(svc.put_chunk, p, sid, idx, data, c)

    @app.post("/v1/uploads/{sid}/complete", status_code=201)
    def complete(sid: str, p: P, c: C) -> dict[str, Any]:
        return svc.complete(p, sid, c)

    @app.get("/v1/uploads/{sid}/inspect")
    def inspect(sid: str, p: P, c: C) -> dict[str, Any]:
        return svc.upload_inspect(p, sid, c)

    # ---- quarantine & triage -----------------------------------------------------------
    @app.post("/v1/quarantine/{sid}/disposition")
    def disposition(sid: str, body: Disposition, p: P, c: C) -> dict[str, Any]:
        return svc.disposition(p, sid, body.decision, body.note, c)

    @app.post("/v1/uploads/{sid}/triage")
    def triage(sid: str, p: P, c: C) -> dict[str, Any]:
        return svc.triage_session(p, sid, c).model_dump()

    # ---- evidence ----------------------------------------------------------------------
    @app.get("/v1/evidence/{eid}")
    def get_evidence(eid: str, p: P, c: C) -> dict[str, Any]:
        return svc.get_evidence(p, eid, c)

    @app.get("/v1/evidence/{eid}/content")
    def content(
        eid: str, p: P, c: C, x_access_reason: Annotated[str, Header()] = ""
    ) -> StreamingResponse:
        it, meta = svc.open_content(p, eid, x_access_reason, c)
        return StreamingResponse(it, media_type=meta["media_type"],
                                 headers={"x-content-sha256": meta["sha256"],
                                          "content-length": str(meta["size"])})  # fmt: skip

    @app.post("/v1/evidence/{eid}/derivatives", status_code=201)
    async def derivative(eid: str, request: Request, p: P, c: C, kind: str,
                         x_params: Annotated[str, Header()] = "{}") -> dict[str, Any]:  # fmt: skip
        data = await request.body()
        mt = request.headers.get("content-type", "application/octet-stream")
        try:
            params = json.loads(x_params)
        except ValueError:
            raise CustodyError("x-params must be JSON") from None
        return await run_in_threadpool(svc.create_derivative, p, eid, kind, data, mt, params, c)

    @app.get("/v1/evidence/{eid}/custody")
    def custody(eid: str, p: P, c: C) -> dict[str, Any]:
        return svc.custody_report(p, eid, c)

    @app.post("/v1/evidence/{eid}/holds", status_code=201)
    def hold_request(eid: str, body: HoldRequest, p: P, c: C) -> dict[str, Any]:
        return svc.request_hold(p, eid, body.case_ref, body.reason, c)

    @app.post("/v1/holds/{hid}/approve")
    def hold_approve(hid: str, p: P, c: C) -> dict[str, Any]:
        return svc.approve_hold(p, hid, c)

    @app.post("/v1/holds/{hid}/release")
    def hold_release(hid: str, p: P, c: C, reason: str = "released") -> dict[str, Any]:
        return svc.release_hold(p, hid, reason, c)

    # ---- audit & alerts ----------------------------------------------------------------
    @app.get("/v1/audit")
    def audit(p: P, c: C, after: int = 0, limit: int = 200) -> dict[str, Any]:
        svc._require(p, "audit:read", c)
        return {"entries": svc.audit.entries(after, limit)}

    @app.post("/v1/audit/verify")
    def audit_verify(p: P, c: C) -> dict[str, Any]:
        svc._require(p, "audit:verify", c)
        s = svc.audit.verify()
        return {"ok": s.ok, "entries": s.entries, "head_hash": s.head_hash,
                "checkpoints_verified": s.checkpoints_verified, "error": s.error}  # fmt: skip

    @app.post("/v1/audit/checkpoint")
    def audit_checkpoint(p: P, c: C) -> dict[str, Any]:
        svc._require(p, "audit:checkpoint", c)
        return svc.audit.checkpoint()

    @app.post("/v1/audit/scan")
    def audit_scan(p: P, c: C) -> dict[str, Any]:
        return {"alerts": svc.scan_audit(p, c)}

    @app.get("/v1/alerts")
    def alerts(p: P, c: C, status: str = "open") -> dict[str, Any]:
        return {"alerts": svc.list_alerts(p, status, c)}

    @app.post("/v1/alerts/{aid}/ack")
    def ack(aid: str, p: P, c: C) -> dict[str, Any]:
        return svc.ack_alert(p, aid, c)

    return app


def main() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run("custody.app:create_app", factory=True, host="0.0.0.0", port=8080,
                log_level="info", proxy_headers=True)  # fmt: skip


if __name__ == "__main__":  # pragma: no cover
    main()
