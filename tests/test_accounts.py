"""Offline OIDC contract/security tests: generated signing keys, no real issuer/cluster."""
import base64
import concurrent.futures
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

from academy import accounts, config, main
from platforms import assert_owner_only

H = {"X-Academy": "1"}
ISSUER = "https://issuer.example"
ENV = {"OIDC_ISSUER": ISSUER, "OIDC_CLIENT_ID": "test-client", "OIDC_CLIENT_SECRET": "test-secret",
       "PUBLIC_URL": "https://localhost", "SESSION_SECRET": "a-test-only-random-session-secret"}


def progress():
    return dict(v=2, lessons={"a": {"seen": 10}}, predictions={}, guesses={}, explains={}, labs={}, cards={},
                confidence={}, diagnostics={}, days=["2026-01-01"], cmds={}, xp=0)


class Provider:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.jwk.update(kid="test-key", alg="RS256", use="sig")
        self.discovery = dict(issuer=ISSUER, authorization_endpoint=ISSUER + "/authorize",
                              token_endpoint=ISSUER + "/token", jwks_uri=ISSUER + "/jwks",
                              code_challenge_methods_supported=["S256"])
        self.calls = []
        self.params = {}
        self.overrides = {}
        self.remove = []
        self.alg = "RS256"
        self.bad_signature = False
        self.omit_kid = False

    def begin(self, client):
        response = client.get("/api/auth/login", follow_redirects=False)
        assert response.status_code == 302
        self.params = {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}
        return response

    def finish(self, client, **params):
        return client.get("/api/auth/callback", params={"state": self.params["state"], "code": "valid-code", **params}, follow_redirects=False)

    def login(self, client):
        self.begin(client)
        response = self.finish(client)
        assert response.status_code == 302, response.text
        return response

    def fetch(self, url, *, data=None, headers=None):
        self.calls.append(url)
        if url.endswith("/.well-known/openid-configuration"):
            return self.discovery
        if url == ISSUER + "/jwks":
            return {"keys": [dict(self.jwk)]}
        assert url == ISSUER + "/token"
        fields = {k: v[0] for k, v in parse_qs(data.decode()).items()}
        if "client_secret_post" in self.discovery.get("token_endpoint_auth_methods_supported", []):
            assert fields["client_secret"] == ENV["OIDC_CLIENT_SECRET"]
            assert fields["client_id"] == ENV["OIDC_CLIENT_ID"]
        else:
            auth = base64.b64decode(headers["Authorization"].split()[1]).decode()
            assert auth == "test-client:test-secret"
        assert fields["grant_type"] == "authorization_code" and fields["code"] == "valid-code"
        assert fields["redirect_uri"] == "https://localhost/api/auth/callback"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(fields["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        assert challenge == self.params["code_challenge"]
        claims = dict(iss=ISSUER, sub="subject-123", aud="test-client", exp=int(time.time()) + 300,
                      iat=int(time.time()), nonce=self.params["nonce"], email="ignored@example.invalid", name="Ignored")
        claims.update(self.overrides)
        for k in self.remove:
            claims.pop(k, None)
        key = self.key
        if self.bad_signature:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if self.alg == "none": key = None
        if self.alg == "HS256": key = "attacker-secret-long-enough-for-hmac-signature"
        return {"id_token": jwt.encode(claims, key, algorithm=self.alg, headers={} if self.omit_kid else {"kid": self.jwk["kid"]}),
                "access_token": "never-persist-this", "refresh_token": "never-persist-this-either"}


@pytest.fixture
def oidc(monkeypatch, tmp_path):
    for key, value in ENV.items(): monkeypatch.setenv("ACADEMY_" + key, value)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    accounts._CACHE.clear()
    provider = Provider()
    monkeypatch.setattr(accounts, "fetch_json", provider.fetch)
    with TestClient(main.app, base_url="https://localhost") as client:
        yield provider, client
    accounts._CACHE.clear()


def test_full_flow_minimal_scope_and_cached_discovery(oidc):
    provider, client = oidc
    meta = client.get("/api/meta").json()
    assert meta["accounts"] is True and meta["account_provider"] == "issuer.example"
    assert not any(x in json.dumps(meta) for x in ("test-secret", "test-client", "/authorize"))
    assert client.get("/api/me").json()["signed_in"] is False
    provider.begin(client)
    assert provider.params["scope"] == "openid"
    assert provider.params["response_type"] == "code"
    assert provider.params["code_challenge_method"] == "S256"
    response = provider.finish(client)
    assert response.status_code == 302 and response.headers["location"] == "https://localhost/me"
    assert client.get("/api/me").json()["signed_in"] is True
    assert client.get("/api/me").json()["display_name"] is None
    assert provider.calls.count(ISSUER + "/.well-known/openid-configuration") == 1
    # A learner session has no effect on cluster permission checks.
    assert client.post("/api/connect", json={"identity": "admin"}, headers=H).status_code == 409
    exported = client.get("/api/me/export").text
    assert "ignored@example" not in exported and "Ignored" not in exported
    with accounts.database() as db:
        assert db.execute("SELECT id FROM sessions").fetchone()[0] != client.cookies[accounts.COOKIE]
    assert b"never-persist-this" not in (config.DATA_DIR / "accounts.sqlite3").read_bytes()
    assert_owner_only(config.DATA_DIR / "accounts.sqlite3")


def test_state_is_bound_to_browser_and_single_use(oidc):
    provider, client = oidc
    provider.begin(client)
    assert provider.finish(client, state="bad-state").status_code == 400
    with TestClient(main.app, base_url="https://localhost") as other:
        assert provider.finish(other).status_code == 400
    assert provider.finish(client).status_code == 302
    assert provider.finish(client).status_code == 400


@pytest.mark.parametrize("overrides", [
    {"nonce": "bad"}, {"aud": "other-client"}, {"iss": "https://other.example"},
    {"exp": 100, "iat": 10}, {"iat": time.time() + 600}, {"azp": "other-client"},
    {"aud": ["test-client", "other"]}, {"sub": ""}, {"iat": "100"}, {"exp": "9999999999"},
    {"nonce": None}, {"exp": float('nan')},
])
def test_bad_claims_rejected(oidc, overrides):
    provider, client = oidc
    provider.overrides = overrides
    provider.begin(client)
    assert provider.finish(client).status_code == 400
    assert client.get("/api/me").json()["signed_in"] is False


@pytest.mark.parametrize("claim", ["iss", "sub", "aud", "exp", "iat", "nonce"])
def test_required_claims(oidc, claim):
    provider, client = oidc
    provider.remove = [claim]
    provider.begin(client)
    assert provider.finish(client).status_code == 400


@pytest.mark.parametrize("alg", ["none", "HS256"])
def test_unsigned_and_hmac_tokens_rejected(oidc, alg):
    provider, client = oidc
    provider.alg = alg
    provider.begin(client)
    assert provider.finish(client).status_code == 400


def test_bad_signature(oidc):
    provider, client = oidc
    provider.bad_signature = True
    provider.begin(client)
    assert provider.finish(client).status_code == 400


def test_es256_and_multiple_audiences_with_azp(oidc):
    provider, client = oidc
    provider.key = ec.generate_private_key(ec.SECP256R1())
    provider.jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(provider.key.public_key()))
    provider.jwk.update(kid="ec", alg="ES256", use="sig")
    provider.alg = "ES256"
    provider.overrides = {"aud": ["test-client", "second"], "azp": "test-client"}
    provider.login(client)


def test_jwks_rotation_and_cache(oidc):
    provider, client = oidc
    provider.login(client)
    provider.jwk["kid"] = "rotated"
    provider.login(client)
    assert provider.calls.count(ISSUER + "/jwks") == 2


@pytest.mark.parametrize("field,value", [("issuer", "https://evil.example"), ("token_endpoint", "http://evil.example/token"), ("jwks_uri", "file:///etc/passwd")])
def test_discovery_validation(oidc, field, value):
    provider, client = oidc
    provider.discovery[field] = value
    assert client.get("/api/auth/login").status_code == 502


def test_post_client_authentication(oidc):
    provider, client = oidc
    provider.discovery["token_endpoint_auth_methods_supported"] = ["client_secret_post"]
    provider.login(client)


@pytest.mark.parametrize("public,secure", [("https://localhost", True), ("http://localhost", False), ("http://127.0.0.1:8768", False)])
def test_cookie_flags(oidc, monkeypatch, public, secure):
    provider, _ = oidc
    monkeypatch.setenv("ACADEMY_PUBLIC_URL", public)
    # Provider fixture verifies the production callback URI; adjust only for this flag test.
    response = accounts.login()
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header
    assert ("secure" in header) is secure and "domain=" not in header
    # Session cookie uses the very same helper.
    session = accounts.Response()
    accounts.cookie(session, accounts.COOKIE, "test-id", accounts.SESSION_TTL, accounts.enabled())
    assert ("secure" in session.headers["set-cookie"].lower()) is secure
    assert "httponly" in session.headers["set-cookie"].lower()


@pytest.mark.parametrize("method,path", [("put", "/api/me/progress"), ("delete", "/api/me"), ("post", "/api/auth/logout")])
def test_csrf(oidc, method, path):
    provider, client = oidc
    provider.login(client)
    assert getattr(client, method)(path).status_code == 403
    assert getattr(client, method)(path, headers={"X-Academy": "wrong"}).status_code == 403
    assert client.options(path, headers={"Origin": "https://evil.example"}).status_code == 403
    assert "access-control-allow-origin" not in client.get("/api/me", headers={"Origin": "https://evil.example"}).headers
    assert client.get("/api/me").json()["signed_in"] is True


def test_concurrency_export_and_delete_all_sessions(oidc):
    provider, client = oidc
    provider.login(client)
    with TestClient(main.app, base_url="https://localhost") as other:
        provider.login(other)
        first = client.get("/api/me/progress")
        assert first.json() == {"progress": None, "version": 0, "updated": None}
        assert first.headers["etag"] == '"0"'
        headers = {**H, "If-Match": '"0"'}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda c: c.put("/api/me/progress", json=progress(), headers=headers), [client, other]))
        assert sorted(r.status_code for r in responses) == [200, 409]
        conflict = next(r for r in responses if r.status_code == 409)
        assert conflict.json()["progress"] == progress() and conflict.headers["etag"] == '"1"'
        assert client.put("/api/me/progress", json=progress(), headers=H).status_code == 409
        assert client.put("/api/me/progress", json=progress(), headers={**H, "If-Match": '"1"'}).json()["version"] == 2
        response = client.get("/api/me/export")
        data = response.json()
        assert data["user"]["issuer"] == ISSUER and data["user"]["sub"] == "subject-123"
        assert data["progress"] == progress() and len(data["sessions"]) == 2
        assert all(set(s) == {"created", "expires"} for s in data["sessions"])
        assert response.headers["cache-control"] == "no-store" and "attachment" in response.headers["content-disposition"]
        assert client.delete("/api/me", headers=H).json() == {"deleted": True}
        assert other.get("/api/me").json()["signed_in"] is False
        assert other.get("/api/me/progress").status_code == 401
        with accounts.database() as db:
            for table in ("users", "progress", "sessions"):
                assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_sessions_logout_expiry_and_secret_rotation(oidc, monkeypatch):
    provider, client = oidc
    provider.login(client)
    assert client.post("/api/auth/logout", headers=H).status_code == 200
    assert client.get("/api/me/progress").status_code == 401
    provider.login(client)
    with accounts.database() as db: db.execute("UPDATE sessions SET expires=0")
    assert client.get("/api/me").json()["signed_in"] is False
    provider.login(client)
    monkeypatch.setenv("ACADEMY_SESSION_SECRET", "different-test-secret")
    assert client.get("/api/me").json()["signed_in"] is False


def test_expired_flow(oidc):
    provider, client = oidc
    provider.begin(client)
    with accounts.database() as db: db.execute("UPDATE flows SET expires=0")
    assert provider.finish(client).status_code == 400


@pytest.mark.parametrize("path", ["/api/me/progress", "/api/me/export"])
def test_auth_required(oidc, path):
    _, client = oidc
    assert client.get(path).status_code == 401
    assert client.delete("/api/me", headers=H).status_code == 401
    assert client.put("/api/me/progress", json=progress(), headers=H).status_code == 401


def test_size_limit_and_shape(oidc):
    provider, client = oidc
    provider.login(client)
    p = progress()
    p["labs"] = {"lab": {"diagnosis": "x" * accounts.MAX_PROGRESS}}
    assert client.put("/api/me/progress", json=p, headers={**H, "If-Match": '"0"'}).status_code == 413
    for body in (b'[]', b'null', b'{"v":2}', b'{broken', b'{"xp":NaN}'):
        assert client.put("/api/me/progress", content=body, headers=H).status_code == 422
    p = progress(); p["email"] = "unwanted"
    assert client.put("/api/me/progress", json=p, headers=H).status_code == 422
    assert client.get("/api/me/progress").json()["version"] == 0


@pytest.mark.parametrize("missing", list(ENV))
def test_incomplete_env_disables_feature(oidc, monkeypatch, missing):
    _, client = oidc
    monkeypatch.delenv("ACADEMY_" + missing)
    assert client.get("/api/meta").json()["accounts"] is False
    assert "account_provider" not in client.get("/api/meta").json()
    for path in ("/api/auth/login", "/api/auth/callback", "/api/me", "/api/me/progress", "/api/me/export"):
        assert client.get(path).status_code == 404
    assert client.post("/api/auth/logout", headers=H).status_code == 404
    assert client.delete("/api/me", headers=H).status_code == 404
    assert not (config.DATA_DIR / "accounts.sqlite3").exists()


def test_no_account_metadata_in_static_export(oidc, tmp_path):
    from scripts.export_static import export
    out = tmp_path / "static"
    out.mkdir()
    (out / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    # This repository currently has known content integrity failures; meta is written first.
    export(out, None)
    meta = json.loads((out / "data/meta.json").read_text(encoding="utf-8"))
    assert meta["mode"] == "static" and "accounts" not in meta and "account_provider" not in meta


def test_expected_account_prevents_cross_account_upload(oidc):
    provider, client = oidc
    provider.login(client)
    scope = client.get('/api/me').json()['sync_key']
    assert client.put('/api/me/progress', json=progress(), headers={**H, 'If-Match': '"0"'}).status_code == 200
    provider.overrides = {'sub': 'second-subject'}
    provider.login(client)
    assert client.get('/api/me').json()['sync_key'] != scope
    headers = {**H, 'X-Academy-Account': scope, 'If-Match': '"0"'}
    assert client.put('/api/me/progress', json=progress(), headers=headers).status_code == 401
    assert client.get('/api/me/progress', headers=headers).status_code == 401
    assert client.delete('/api/me', headers=headers).status_code == 401
    assert client.post('/api/auth/logout', headers=headers).status_code == 401
    assert client.get('/api/me').json()['signed_in'] is True
    assert client.get('/api/me/progress').json()['version'] == 0


def test_small_clock_skew(oidc):
    provider, client = oidc
    provider.overrides = {'iat': time.time() - 100, 'exp': time.time() - 30}
    provider.login(client)
    provider.overrides = {'iat': time.time() + 30}
    provider.login(client)


def test_weak_rsa_key_rejected(oidc):
    provider, client = oidc
    provider.key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    provider.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(provider.key.public_key()))
    provider.jwk.update(kid='weak', alg='RS256', use='sig')
    provider.begin(client)
    assert provider.finish(client).status_code == 400


def test_bounded_fetch_timeout_and_no_redirects(monkeypatch):
    payload = b'{"ok":true}'
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, n):
            assert n == 256 * 1024 + 1
            return payload[:n]
    class Opener:
        def open(self, req, timeout):
            assert timeout == 10
            assert req.full_url == 'https://issuer.example/discovery'
            return Reply()
    def build(handler):
        assert isinstance(handler, accounts.NoRedirect)
        assert handler.redirect_request(None, None, 302, '', {}, 'https://other.example') is None
        return Opener()
    monkeypatch.setattr(accounts, 'build_opener', build)
    assert accounts.fetch_json('https://issuer.example/discovery') == {'ok': True}
    payload = b'x' * (256 * 1024 + 1)
    with pytest.raises(ValueError, match='too large'):
        accounts.fetch_json('https://issuer.example/discovery')
    payload = b'[]'
    with pytest.raises(ValueError, match='invalid OIDC response'):
        accounts.fetch_json('https://issuer.example/discovery')
    with pytest.raises(ValueError, match='unsafe'):
        accounts.fetch_json('http://issuer.example/discovery')


def test_cache_control_including_errors(oidc):
    _, client = oidc
    for response in (client.get('/api/me'), client.get('/api/me/progress'), client.get('/api/auth/callback'),
                     client.post('/api/auth/logout')):
        assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('public', ['http://academy.example', 'file:///tmp/x', 'https://localhost:bad', 'https://user:secret@localhost', 'https://['])
def test_invalid_public_url_disables_accounts(oidc, monkeypatch, public):
    _, client = oidc
    monkeypatch.setenv('ACADEMY_PUBLIC_URL', public)
    assert client.get('/api/meta').json()['accounts'] is False


def test_token_without_kid_with_one_eligible_key(oidc):
    provider, client = oidc
    provider.omit_kid = True
    provider.login(client)


def test_exact_issuer_preserves_trailing_slash(oidc, monkeypatch):
    provider, client = oidc
    monkeypatch.setenv('ACADEMY_OIDC_ISSUER', ISSUER + '/')
    provider.discovery['issuer'] = ISSUER + '/'
    provider.overrides['iss'] = ISSUER + '/'
    provider.login(client)
    assert client.get('/api/me/export').json()['user']['issuer'] == ISSUER + '/'


def test_same_subject_on_another_issuer_is_a_different_account(oidc, monkeypatch):
    provider, client = oidc
    provider.login(client)
    assert client.put('/api/me/progress', json=progress(), headers={**H, 'If-Match': '"0"'}).status_code == 200
    second = 'https://second.example'
    monkeypatch.setenv('ACADEMY_OIDC_ISSUER', second)
    provider.discovery['issuer'] = second
    provider.overrides['iss'] = second
    provider.login(client)
    assert client.get('/api/me/progress').json()['progress'] is None
    assert client.get('/api/me/export').json()['user']['issuer'] == second
    with accounts.database() as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 2


def test_retained_note_alternatives_round_trip_in_export(oidc):
    provider, client = oidc
    provider.login(client)
    p = progress()
    p['syncNotes'] = {'["lab","draft"]': ['draft from first device', 'draft from second device']}
    assert client.put('/api/me/progress', json=p, headers={**H, 'If-Match': '"0"'}).status_code == 200
    assert client.get('/api/me/export').json()['progress']['syncNotes'] == p['syncNotes']
