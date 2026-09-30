"""Operator CLI: keys, dev tokens, audit verification, fixity, expiry, demo."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time

from .app import build_service
from .audit import Ctx
from .auth import Role, issue_token
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="custody-admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="print fresh signing key and token secret")
    t = sub.add_parser("issue-token", help="DEV ONLY bearer token")
    t.add_argument("--sub", required=True)
    t.add_argument("--role", required=True, choices=[r.value for r in Role])
    t.add_argument("--agency", required=True)
    t.add_argument("--ttl", type=int, default=900)
    for name in ("verify-audit", "checkpoint", "fixity", "expire", "scan"):
        sub.add_parser(name)
    sub.add_parser("demo", help="run the end-to-end simulation")
    a = ap.parse_args(argv)

    if a.cmd == "init":
        print(
            f"CUSTODY_SIGNING_KEY={secrets.token_hex(32)}\nCUSTODY_TOKEN_SECRET={secrets.token_hex(32)}"
        )
        return 0
    if a.cmd == "demo":
        from .simulate import run_demo

        return run_demo()
    s = Settings.from_env()
    if a.cmd == "issue-token":
        print(
            issue_token(
                s.token_secret, a.sub, Role(a.role), a.agency, int(time.time() * 1000), a.ttl
            )
        )
        return 0
    svc = build_service(s)
    if a.cmd == "verify-audit":
        st = svc.audit.verify()
        print(
            json.dumps(
                {"ok": st.ok, "entries": st.entries, "head": st.head_hash, "error": st.error}
            )
        )
        return 0 if st.ok else 2
    if a.cmd == "checkpoint":
        print(json.dumps(svc.audit.checkpoint()))
    elif a.cmd == "fixity":
        res = svc.run_fixity()
        print(json.dumps(res))
        return 0 if not res["failed"] else 2
    elif a.cmd == "expire":
        print(json.dumps({"expired": svc.expire_stale()}))
    elif a.cmd == "scan":
        from .audit import Actor  # noqa: F401
        from .auth import Principal

        p = Principal("cli-auditor", Role.AUDITOR, "*")
        print(json.dumps({"alerts": svc.scan_audit(p, Ctx(ip="cli"))}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
