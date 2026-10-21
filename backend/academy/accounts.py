"""Optional learner identity and progress. No imports or privileges from cluster/author code."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import math
import os
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlsplit, quote_plus
from urllib.request import Request as URLRequest, build_opener, HTTPRedirectHandler

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import config

log = logging.getLogger(__name__)

COOKIE = "academy_session"
FLOW_COOKIE = "academy_oidc"
MAX_PROGRESS = 2 * 1024 * 1024
SESSION_TTL = 30 * 86400
FLOW_TTL = 600
SKEW = 60
_CACHE: dict[str, tuple[float, dict]] = {}


@dataclass(frozen=True)
class Settings:
    issuer: str
    client_id: str
    client_secret: str
    public_url: str
    secret: str

    @property
    def secure(self):
        u = urlsplit(self.public_url)
        return not (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1"))

    @property
    def provider(self):
        return "Google" if self.issuer == "https://accounts.google.com" else urlsplit(self.issuer).hostname

    @property
    def callback(self):
        return self.public_url + "/api/auth/callback"


def _safe_url(value: str, *, allow_query=False) -> bool:
    try:
        u = urlsplit(value)
        _ = u.port
    except (ValueError, TypeError):
        return False
    return bool(u.hostname and not u.username and not u.password and (allow_query or not u.query) and not u.fragment
                and (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1"))))


def settings() -> Settings | None:
    vals = [os.environ.get("ACADEMY_" + k, "").strip() for k in
            ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "PUBLIC_URL", "SESSION_SECRET")]
    if not all(vals):
        return None
    vals[3] = vals[3].rstrip("/")
    if not _safe_url(vals[0]) or not _safe_url(vals[3]):
        return None
    import importlib.util

    if importlib.util.find_spec("jwt") is None:  # optional dependency: pip install -r requirements-accounts.txt
        log.warning("sign-in is configured but PyJWT is not installed (requirements-accounts.txt); accounts stay off")
        return None
    return Settings(*vals)


def metadata() -> dict:
    s = settings()
    return {"accounts": bool(s), **({"account_provider": s.provider} if s else {})}


def enabled() -> Settings:
    s = settings()
    if not s:
        raise HTTPException(404, "Accounts are disabled")
    return s


def csrf(request: Request):
    if request.method not in ("GET", "HEAD") and request.headers.get("x-academy") != "1":
        raise HTTPException(403, "missing X-Academy header")


router = APIRouter(dependencies=[Depends(csrf)])


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(url: str, *, data: bytes | None = None, headers: dict | None = None) -> dict:
    """Bounded, TLS-verified, no-redirect HTTP; replaced by the fake issuer in tests."""
    if not _safe_url(url, allow_query=True):
        raise ValueError("unsafe OIDC endpoint")
    req = URLRequest(url, data=data, headers={"Accept": "application/json", **(headers or {})})
    with build_opener(NoRedirect()).open(req, timeout=10) as r:
        body = r.read(256 * 1024 + 1)
    if len(body) > 256 * 1024:
        raise ValueError("OIDC response too large")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("invalid OIDC response")
    return result


def cached(url: str, *, refresh=False) -> dict:
    entry = _CACHE.get(url)
    if not refresh and entry and entry[0] > time.time():
        return entry[1]
    result = fetch_json(url)
    _CACHE[url] = (time.time() + 3600, result)
    return result


def discovery(s: Settings) -> dict:
    d = cached(s.issuer.rstrip("/") + "/.well-known/openid-configuration")
    if d.get("issuer") != s.issuer or any(not _safe_url(d.get(k, ""), allow_query=True) for k in
                                               ("authorization_endpoint", "token_endpoint", "jwks_uri")):
        raise ValueError("invalid discovery")
    if "S256" not in d.get("code_challenge_methods_supported", ["S256"]):
        raise ValueError("issuer does not support S256")
    return d


def digest(s: Settings, token: str) -> str:
    return hmac.new(s.secret.encode(), token.encode(), hashlib.sha256).hexdigest()


@contextmanager
def database():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = config.DATA_DIR / "accounts.sqlite3"
    # Create privately before SQLite opens it (also avoids a permissive creation window).
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA secure_delete=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, issuer TEXT NOT NULL, sub TEXT NOT NULL,
            created REAL NOT NULL, display_name TEXT, UNIQUE(issuer, sub));
        CREATE TABLE IF NOT EXISTS progress (
            user INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            json TEXT NOT NULL, version INTEGER NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created REAL NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS flows (
            state TEXT PRIMARY KEY, browser TEXT NOT NULL, verifier TEXT NOT NULL,
            nonce TEXT NOT NULL, expires REAL NOT NULL);
    """)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute("DELETE FROM flows WHERE expires < ?", (time.time(),))
            yield db
    finally:
        db.close()


def cookie(resp: Response, name: str, value: str, ttl: int, s: Settings):
    resp.set_cookie(name, value, max_age=ttl, httponly=True, secure=s.secure, samesite="lax", path="/")


def private(resp: Response):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def current(request: Request, s: Settings, db):
    token = request.cookies.get(COOKIE, "")
    return db.execute("""SELECT u.* FROM users u JOIN sessions s ON u.id=s.user
                         WHERE s.id=? AND s.expires>? AND u.issuer=?""",
                      (digest(s, token), time.time(), s.issuer)).fetchone() if token else None


def sync_key(s, user):
    return digest(s, "sync:" + str(user["id"]) + ":" + str(user["created"]))


def require_user(request, s, db):
    user = current(request, s, db)
    if user is None:
        raise HTTPException(401, "Sign in to sync progress")
    expected = request.headers.get("x-academy-account")
    if expected is not None and not hmac.compare_digest(expected, sync_key(s, user)):
        raise HTTPException(401, "Account changed; review a new merge")
    return user


def progress_copy(db, user) -> dict:
    p = db.execute("SELECT * FROM progress WHERE user=?", (user,)).fetchone()
    return {"progress": json.loads(p["json"]) if p else None, "version": p["version"] if p else 0,
            "updated": p["updated"] if p else None}


def progress_response(copy, status=200):
    return private(JSONResponse(copy, status_code=status, headers={"ETag": f'"{copy["version"]}"'}))


@router.get("/api/auth/login")
def login():
    s = enabled()
    try:
        d = discovery(s)
    except Exception:
        raise HTTPException(502, "Identity provider unavailable") from None
    state, browser, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(4))
    with database() as db:
        db.execute("INSERT INTO flows VALUES (?, ?, ?, ?, ?)",
                   (digest(s, state), digest(s, browser), verifier, nonce, time.time() + FLOW_TTL))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = dict(response_type="code", client_id=s.client_id, redirect_uri=s.callback, scope="openid",
                  state=state, nonce=nonce, code_challenge=challenge, code_challenge_method="S256")
    resp = RedirectResponse(d["authorization_endpoint"] + ("&" if "?" in d["authorization_endpoint"] else "?") + urlencode(params), status_code=302)
    cookie(resp, FLOW_COOKIE, browser, FLOW_TTL, s)
    return private(resp)


def verify_token(token: str, s: Settings, d: dict, nonce: str) -> dict:
    import jwt

    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    if alg not in ("RS256", "ES256") or header.get("crit"):
        raise ValueError("unsupported algorithm")
    keys = cached(d["jwks_uri"]).get("keys", [])
    def matching(keys):
        return [k for k in keys if ("kid" not in header or k.get("kid") == header["kid"]) and k.get("use", "sig") == "sig"
                and k.get("alg", alg) == alg and "verify" in k.get("key_ops", ["verify"])
                and k.get("kty") == ("RSA" if alg == "RS256" else "EC")
                and (alg != "ES256" or k.get("crv") == "P-256")]
    candidates = matching(keys)
    if not candidates:
        candidates = matching(cached(d["jwks_uri"], refresh=True).get("keys", []))
    if len(candidates) != 1:
        raise ValueError("unknown or ambiguous signing key")
    key = jwt.PyJWK.from_dict(candidates[0], algorithm=alg).key
    if alg == "RS256" and key.key_size < 2048:
        raise ValueError("RSA key is too small")
    claims = jwt.decode(token, key, algorithms=[alg], audience=s.client_id, issuer=s.issuer, leeway=SKEW,
                        options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]})
    if not isinstance(claims["sub"], str) or not claims["sub"] or len(claims["sub"]) > 255:
        raise ValueError("invalid subject")
    if any(type(claims[k]) not in (int, float) or not math.isfinite(claims[k]) for k in ("iat", "exp")):
        raise ValueError("invalid times")
    if claims["exp"] <= claims["iat"]:
        raise ValueError("invalid lifetime")
    if not isinstance(claims["nonce"], str) or not hmac.compare_digest(claims["nonce"], nonce):
        raise ValueError("invalid nonce")
    if "azp" in claims and claims["azp"] != s.client_id:
        raise ValueError("invalid authorized party")
    if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != s.client_id:
        raise ValueError("missing authorized party")
    return claims


@router.get("/api/auth/callback")
def callback(request: Request):
    s = enabled()
    state = request.query_params.get("state", "")
    browser = request.cookies.get(FLOW_COOKIE, "")
    with database() as db:
        flow = db.execute("SELECT * FROM flows WHERE state=? AND expires>?", (digest(s, state), time.time())).fetchone()
        if not flow or not browser or not hmac.compare_digest(flow["browser"], digest(s, browser)):
            raise HTTPException(400, "Invalid or expired sign-in state")
        db.execute("DELETE FROM flows WHERE state=?", (digest(s, state),))
    code = request.query_params.get("code", "")
    if not code or request.query_params.get("error"):
        raise HTTPException(400, "Sign-in was not completed")
    try:
        d = discovery(s)
        fields = dict(grant_type="authorization_code", code=code, redirect_uri=s.callback, code_verifier=flow["verifier"])
        methods = d.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if "client_secret_basic" in methods:
            auth = quote_plus(s.client_id, safe="") + ":" + quote_plus(s.client_secret, safe="")
            headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
        elif "client_secret_post" in methods:
            fields.update(client_id=s.client_id, client_secret=s.client_secret)
        else:
            raise ValueError("unsupported client authentication")
        tokens = fetch_json(d["token_endpoint"], data=urlencode(fields).encode(), headers=headers)
        claims = verify_token(tokens["id_token"], s, d, flow["nonce"])
    except Exception:
        raise HTTPException(400, "Identity provider response could not be verified") from None
    sid = secrets.token_urlsafe(32)
    with database() as db:
        db.execute("INSERT OR IGNORE INTO users(issuer,sub,created) VALUES (?,?,?)", (s.issuer, claims["sub"], time.time()))
        user = db.execute("SELECT id FROM users WHERE issuer=? AND sub=?", (s.issuer, claims["sub"])).fetchone()[0]
        # Rotate any existing session in this browser on sign-in.
        db.execute("DELETE FROM sessions WHERE id=?", (digest(s, request.cookies.get(COOKIE, "")),))
        db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (digest(s, sid), user, time.time(), time.time() + SESSION_TTL))
    resp = RedirectResponse(s.public_url + "/me", status_code=302)
    cookie(resp, COOKIE, sid, SESSION_TTL, s)
    resp.delete_cookie(FLOW_COOKIE, path="/", secure=s.secure, httponly=True, samesite="lax")
    return private(resp)


@router.post("/api/auth/logout")
def logout(request: Request):
    s = enabled()
    with database() as db:
        if request.headers.get("x-academy-account") is not None:
            require_user(request, s, db)
        db.execute("DELETE FROM sessions WHERE id=?", (digest(s, request.cookies.get(COOKIE, "")),))
    resp = JSONResponse({"signed_in": False})
    resp.delete_cookie(COOKIE, path="/", secure=s.secure, httponly=True, samesite="lax")
    return private(resp)


@router.get("/api/me")
def me(request: Request):
    s = enabled()
    with database() as db:
        user = current(request, s, db)
        if user is None:
            return private(JSONResponse({"signed_in": False, "provider": s.provider}))
        p = progress_copy(db, user["id"])
        return private(JSONResponse({"signed_in": True, "provider": s.provider, "display_name": None,
                                     "sync_key": sync_key(s, user),
                                     "stored": {"progress": p["progress"] is not None, "version": p["version"], "updated": p["updated"]}}))


@router.get("/api/me/progress")
def get_progress(request: Request):
    s = enabled()
    with database() as db:
        user = require_user(request, s, db)
        return progress_response(progress_copy(db, user["id"]))


def validate_progress(raw):
    maps = ("lessons", "predictions", "guesses", "explains", "labs", "cards", "confidence", "diagnostics", "cmds")
    allowed = {"v", *maps, "days", "xp", "last", "route", "legacy", "syncNotes"}
    if (not isinstance(raw, dict) or raw.get("v") != 2 or set(raw) - allowed
            or any(not isinstance(raw.get(k), dict) for k in maps)
            or not isinstance(raw.get("days"), list) or any(not isinstance(d, str) for d in raw["days"])
            or type(raw.get("xp")) not in (int, float)
            or any(k in raw and not isinstance(raw[k], dict) for k in ("last", "legacy", "syncNotes"))
            or ("route" in raw and not isinstance(raw["route"], str))):
        raise HTTPException(422, "Expected a version 2 academy progress object")


@router.put("/api/me/progress")
async def put_progress(request: Request):
    s = enabled()
    # Authenticate before reading an upload, and bound even chunked requests.
    with database() as db:
        user = require_user(request, s, db)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_PROGRESS:
            raise HTTPException(413, "Progress exceeds 2 MB")
    try:
        raw = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, "Invalid JSON") from None
    validate_progress(raw)
    try:
        text = json.dumps(raw, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (ValueError, RecursionError):
        raise HTTPException(422, "Invalid JSON") from None
    if len(text.encode()) > MAX_PROGRESS:
        raise HTTPException(413, "Progress exceeds 2 MB")
    with database() as db:
        # Acquire the write lock before comparing; two devices cannot both win a version.
        user = require_user(request, s, db)
        copy = progress_copy(db, user["id"])
        if request.headers.get("if-match") != f'"{copy["version"]}"':
            return progress_response(copy, 409)
        version = copy["version"] + 1
        db.execute("INSERT INTO progress VALUES (?,?,?,?) ON CONFLICT(user) DO UPDATE SET json=excluded.json, version=excluded.version, updated=excluded.updated",
                   (user["id"], text, version, time.time()))
        return progress_response(progress_copy(db, user["id"]))


@router.get("/api/me/export")
def export(request: Request):
    s = enabled()
    with database() as db:
        user = require_user(request, s, db)
        sessions = [dict(row) for row in db.execute("SELECT created,expires FROM sessions WHERE user=?", (user["id"],))]
        resp = JSONResponse({"user": dict(user), **progress_copy(db, user["id"]), "sessions": sessions},
                            headers={"Content-Disposition": 'attachment; filename="academy-account.json"'})
        return private(resp)


@router.delete("/api/me")
def delete(request: Request):
    s = enabled()
    with database() as db:
        user = require_user(request, s, db)
        db.execute("DELETE FROM users WHERE id=?", (user["id"],))
    resp = JSONResponse({"deleted": True})
    resp.delete_cookie(COOKIE, path="/", secure=s.secure, httponly=True, samesite="lax")
    return private(resp)
