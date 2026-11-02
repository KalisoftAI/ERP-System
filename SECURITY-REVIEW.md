# Deployment Security Review — Kalika ERP

> Reviewed: branch `feature/quote-pdf-vci-packaging-roadmap` (same code as deployed `master`).
> Scope: Docker/Cloud Run deploy path, FastAPI backend, auth, file handling, secrets hygiene.

## Verdict

**2 HIGH** issues to fix before next deploy, 7 medium/low hardening items. Overall the base is good: non-root container, Secret Manager for DB password, `.env` never committed, all routers auth-protected, parameterized ORM queries, bcrypt hashing, audit logging on mutations.

---

## HIGH 1 — JWT secret deployed as a plain env var (`deploy.sh`)

`deploy.sh` line 118–127: `JWT_SECRET` is passed via `--set-env-vars`, so the secret value is stored **in plaintext** on the Cloud Run revision and is readable by anyone with `run.services.get` (Cloud Console → YAML tab shows it). The DB password is already done correctly with `--set-secrets` — do the same for JWT:

```bash
# BEFORE (current)
--set-env-vars="...,JWT_SECRET=${JWT_SECRET},..."

# AFTER (fix)
--set-secrets="CLOUD_SQL_DB_PASS=$DB_SECRET:latest,JWT_SECRET=$JWT_SECRET_NAME:latest"
```

Then drop the `JWT_SECRET="$(gcloud secrets versions access ...)"` fetch in the script entirely — Cloud Run injects it directly; the value never touches shell history/logs.

## HIGH 2 — Path traversal in SPA catch-all (`main.py`)

```python
def _serve_frontend(path: str):
    target = _FRONTEND_DIST / path      # path comes from URL, e.g. /..%2F..%2Fapp%2Fmain.py
    if target.is_file():
        return FileResponse(target)     # serves files OUTSIDE dist/
```

Starlette URL-decodes the path before routing, so `GET /..%2F..%2Fapp%2Fmain.py` (with a non-HTML Accept header, skipping the SPA middleware) resolves outside `frontend/dist` and leaks backend source. Fix:

```python
def _serve_frontend(path: str):
    index = _FRONTEND_DIST / "index.html"
    if not index.exists():
        return RedirectResponse(url="/docs")
    target = (_FRONTEND_DIST / path).resolve()
    # NEW: reject anything escaping the dist directory
    if not target.is_relative_to(_FRONTEND_DIST.resolve()):
        return FileResponse(index)
    if target.is_file():
        return FileResponse(target)
    return FileResponse(index)
```

Apply the same guard to the `/assets` mount if it ever switches to a custom handler (current `StaticFiles` is safe).

---

## MEDIUM

| # | Item | Where | Fix |
|---|------|-------|-----|
| M1 | **No login throttling** — Cloud Run is public (`--allow-unauthenticated`), `/auth/login` allows unlimited attempts (bcrypt slows but doesn't stop brute force) | `routers/auth.py` | Track failures per username/IP; lock 15 min after 5 failures; or add Cloud Armor rate-limit rule |
| M2 | **Weak password policy** — min length 6 | `auth.py:change_password`, `schemas.UserCreate` | Enforce ≥ 10 chars + letter/digit mix |
| M3 | **`/docs`, `/redoc`, `/openapi.json` public in prod** (root even redirects to `/docs` when no frontend build) | `main.py` | `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` when `not settings.DEBUG`; or protect behind auth |
| M4 | **Unbounded upload reads** — `await file.read()` on import endpoints; crafted XLSX = zip bomb. Cloud Run's 32 MB request cap is the only guard | 5 import endpoints | `content = await file.read(); if len(content) > 10*1024*1024: raise 413` |
| M5 | **CORS** — `allow_methods=["*"]`, `allow_headers=["*"]`, and localhost origins always included in production | `main.py` | Explicit methods `["GET","POST","PATCH","DELETE"]`; add localhost origins only when `settings.DEBUG` |
| M6 | **Gmail SMTP password as plain env var** | deploy env | Move `MAIL_PASSWORD` to Secret Manager (`--set-secrets`), same pattern as DB password |
| M7 | **JWT default `"change-me-in-production"`** used silently if env var missing | `config.py` | On startup: `if settings.JWT_SECRET == "change-me-in-production" and not settings.DEBUG: raise RuntimeError(...)` |

## LOW / Notes

- `/health` returns DB error detail + app version — keep the shape but return generic `{"status": "degraded"}` for DB failures in prod.
- JWT 8 h expiry with no revocation — acceptable for an internal ERP; consider shorter tokens + refresh when usage grows.
- `deploy.sh` line 98: `echo "... $(openssl rand -hex 32) ..."` executes the substitution just to print a hint — cosmetic, but quote it or pre-generate.
- New quote/VCI code (ROADMAP-DETAILS): follows auth patterns (`CurrentUser`/`AllStaff`), recipient validation, filename sanitization — no new issues. One note: `_next_quote_no` can race under concurrent creates; catch `IntegrityError` on the unique `quote_no` and retry with seq+1.
- Enable Artifact Registry image scanning (on-push) and add `pip-audit` to CI — current pins (`fastapi 0.115.6`, `python-multipart 0.0.20`, `reportlab 4.2.5`, `PyJWT 2.10.1`) have no known critical CVEs today, but this should be automated.

## What's already good ✅

- `.env` git-ignored **and** never in git history; `.dockerignore` excludes secrets from the image
- DB password via Secret Manager; never echoed
- Non-root container user, slim base images, no build tools in runtime stage
- All API routers behind auth; role-gated writes (`ManagerOrAdmin`/`AllStaff`/admin)
- SQLAlchemy ORM everywhere; only f-string SQL is static DDL in idempotent migrations (no user input)
- Report/download filenames sanitized (`safe_name` alnum filter)
- Audit log on create/update/delete/login/email actions
- Email service never logs credentials; TLS enabled
