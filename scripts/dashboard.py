"""Small authenticated dashboard for the AES research runner."""
from collections import deque
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import adopt
import dashboard_auth
import innovation
import translate

HOST = os.environ.get("AES_DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", os.environ.get("AES_DASHBOARD_PORT", "8080")))
USERNAME = os.environ.get("AES_DASHBOARD_USER", "aes")
PASSWORD = os.environ.get("AES_DASHBOARD_PASSWORD", "")
MAX_STATE_READ = 2_000_000
MAX_DISCOVERIES = 400
MAX_RUN_HISTORY = 12
MAX_POST_BYTES = 4096
TRIAGE_STATES = {"new", "interesting", "dismissed"}
_process_lock = threading.Lock()
_triage_lock = threading.Lock()
_manual_process = None
_manual_started_at = None
_translated_after_run = True

PAGE_PATH = Path(__file__).with_name("dashboard.html")
PAGE = PAGE_PATH.read_text(encoding="utf-8")
LOGIN_PAGE = PAGE_PATH.with_name("dashboard_login.html").read_text(encoding="utf-8")
SESSION_COOKIE = "aes_session"
POST_ROUTES = {"/api/login", "/api/logout", "/api/password", "/api/run", "/api/triage",
               "/api/users/create", "/api/users/reset", "/api/users/role", "/api/users/delete"}
ADOPTION_ROUTES = {"/api/translate", "/api/adoption/settings", "/api/projects/add", "/api/projects/remove", "/api/adoptions/preview",
                   "/api/adoptions/deploy", "/api/adoptions/discard", "/api/adoptions/revert"}
POST_ROUTES |= ADOPTION_ROUTES


def _read_jsonl(path, keep=None):
    """Read dict rows from a JSONL file, skipping malformed lines; keep only the last ``keep`` when given."""
    rows = deque(maxlen=keep)
    try:
        with path.open("rb") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        return []
    return list(rows)


def _https_or_none(value):
    return value if isinstance(value, str) and urlsplit(value).scheme == "https" else None


def _key(source):
    return (source or "").strip().lower()


def _load_sources():
    try:
        config = json.loads(innovation.SOURCES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    sources = config.get("sources") if isinstance(config, dict) else None
    return [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else []


def _triage_path():
    return innovation.STATE / "research" / "triage.jsonl"


def _triage_map():
    result = {}
    for row in _read_jsonl(_triage_path()):
        if row.get("state") in TRIAGE_STATES and isinstance(row.get("source"), str):
            result[_key(row["source"])] = row["state"]
    return result


def _run_summary(row):
    return {"finished_at": row.get("finished_at"), "duration_seconds": row.get("duration_seconds"),
            "fetched": row.get("fetched", 0), "new": row.get("new", 0),
            "source_errors_count": len(row.get("source_errors") or [])}


def dashboard_status():
    state = innovation.STATE
    research = state / "research"
    runs = _read_jsonl(research / "runs.jsonl", keep=200)
    register = _read_jsonl(research / "register.jsonl")
    digest_files = sorted((research / "digests").glob("*.md"), reverse=True) if (research / "digests").exists() else []
    digest_name, digest = None, ""
    if digest_files:
        digest_name = digest_files[0].name
        try:
            digest = digest_files[0].read_text(encoding="utf-8")[-MAX_STATE_READ:]
        except OSError:
            digest = "Digest não pôde ser lido."
    run = runs[-1] if runs else None
    if run:
        run = {key: run.get(key) for key in (
            "started_at", "finished_at", "duration_seconds", "sources_configured", "source_counts",
            "fetched", "new", "rejected_by_sensitivity_rules")}
        run["source_counts"] = run.get("source_counts") or []
        run["source_errors_count"] = len((runs[-1].get("source_errors") or []))
    global _translated_after_run
    with _process_lock:
        running = _manual_process is not None and _manual_process.poll() is None
        manual_attempt = ({"started_at": _manual_started_at, "running": running,
                           "exit_code": None if running else _manual_process.poll()}
                          if _manual_process is not None else None)
        if manual_attempt and not running and not _translated_after_run:
            _translated_after_run = True
            translate.trigger()

    # Per-source health comes from the most recent run that consulted or failed each source.
    last_items, last_errors = {}, {}
    for row in runs:
        for count in row.get("source_counts") or []:
            last_items[count.get("source_id")] = count.get("items")
            last_errors.pop(count.get("source_id"), None)
        for error in row.get("source_errors") or []:
            last_errors[error.get("source_id")] = error.get("error")
            last_items.pop(error.get("source_id"), None)
    sources = [{"id": s.get("id"), "name": s.get("name") or s.get("id"), "url": _https_or_none(s.get("url")),
                "enabled": bool(s.get("enabled", True)), "items": last_items.get(s.get("id")),
                "topics": [str(t)[:40] for t in (s.get("topics") or []) if isinstance(t, str)][:8],
                "error": last_errors.get(s.get("id"))} for s in _load_sources()]

    triage = _triage_map()
    discoveries = [row for row in register if row.get("kind") == "discovery"]
    triage_counts = {state_name: 0 for state_name in TRIAGE_STATES}
    for row in discoveries:
        triage_counts[triage.get(_key(row.get("source")), "new")] += 1

    latest_proposals = {}
    for row in register:
        if row.get("kind") == "proposal":
            latest_proposals[(_key(row.get("source")), _key(row.get("title")))] = row
    proposals = [{"title": str(p.get("title", ""))[:240], "url": _https_or_none(p.get("source")),
                  "decision": p.get("decision"), "priority": p.get("priority"), "revision": p.get("revision", 1),
                  "recorded_at": p.get("recorded_at")}
                 for p in sorted(latest_proposals.values(), key=lambda p: p.get("recorded_at") or "", reverse=True)]

    return {"state_available": state.exists(), "running": running, "latest_run": run,
            "discovery_count": len(discoveries),
            "proposal_count": sum(row.get("kind") == "proposal" for row in register),
            "triage_counts": triage_counts, "sources": sources, "proposals": proposals[:20],
            "run_history": [_run_summary(row) for row in runs[-MAX_RUN_HISTORY:]],
            "manual_attempt": manual_attempt, "translation": dict(translate.status),
            "digest_name": digest_name, "digest": digest}


def dashboard_discoveries():
    register = _read_jsonl(innovation.STATE / "research" / "register.jsonl")
    triage = _triage_map()
    translations = translate.load()
    names = {s.get("url"): s.get("name") for s in _load_sources()}
    rows = [row for row in register if row.get("kind") == "discovery" and isinstance(row.get("source"), str)]
    rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("recorded_at") or "")), reverse=True)
    discoveries, feeds = [], {}
    prefix = "RSS/Atom metadata from "
    for row in rows[:MAX_DISCOVERIES]:
        feed = row.get("source_feed") if isinstance(row.get("source_feed"), str) else ""
        feed_name = names.get(feed) or urlsplit(feed).hostname or "Fonte desconhecida"
        summary = str(row.get("evidence") or "")
        # Strip the generated "RSS/Atom metadata from <name>." prefix; the feed name is shown separately.
        if summary.startswith(prefix):
            summary = summary.split(". ", 1)[1] if ". " in summary else ""
        discoveries.append({
            "title": str(row.get("title", ""))[:240], "source": row["source"],
            "url": _https_or_none(row["source"]), "date": row.get("date"), "summary": summary[:500],
            "topics": [str(t)[:40] for t in (row.get("topics") or []) if isinstance(t, str)][:8],
            "feed": feed, "feed_name": feed_name, "status": row.get("status"),
            "triage": triage.get(_key(row["source"]), "new"),
            "title_pt": translations.get(_key(row["source"]), {}).get("title"),
            "summary_pt": translations.get(_key(row["source"]), {}).get("summary")})
        entry = feeds.setdefault(feed, {"feed": feed, "name": feed_name, "count": 0})
        entry["count"] += 1
    return {"discoveries": discoveries, "total": len(rows),
            "feeds": sorted(feeds.values(), key=lambda f: f["name"].lower())}


def set_triage(source, triage_state):
    """Append a triage decision for a recorded discovery. Returns False if the discovery is unknown."""
    if triage_state not in TRIAGE_STATES or not isinstance(source, str) or not source or len(source) > 2048:
        raise ValueError("invalid triage request")
    register = _read_jsonl(innovation.STATE / "research" / "register.jsonl")
    if not any(row.get("kind") == "discovery" and _key(row.get("source")) == _key(source) for row in register):
        return False
    path = _triage_path()
    with _triage_lock:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "source": source,
                                "state": triage_state}, ensure_ascii=False) + "\n")
        if os.name != "nt":
            path.chmod(0o600)
    return True


def start_research():
    global _manual_process, _manual_started_at, _translated_after_run
    with _process_lock:
        if _manual_process is not None and _manual_process.poll() is None:
            return False
        state = innovation.STATE
        log = state / "research" / "dashboard-run.log"
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = log.open("ab")
        try:
            _manual_process = subprocess.Popen(
                [sys.executable, str(innovation.SCRIPT_DIR / "innovation.py"), "research", "--per-source", "10"],
                cwd=str(innovation.ROOT), env=os.environ.copy(), stdin=subprocess.DEVNULL,
                stdout=handle, stderr=subprocess.STDOUT, close_fds=True)
            _manual_started_at = datetime.now(timezone.utc).isoformat()
            _translated_after_run = False
        finally:
            handle.close()
        return True


CSP = ("default-src 'self'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AESDashboard"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Avoid recording paths, credentials, or user-supplied data in access logs.
        return

    def _token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _client(self):
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return forwarded or self.client_address[0]

    def _require(self, admin=False, allow_pending=False):
        user = dashboard_auth.session_user(self._token())
        if not user:
            self._json(401, {"error": "login required"})
            return None
        if user["must_change"] and not allow_pending:
            self._json(403, {"error": "password change required"})
            return None
        if admin and user["role"] != "admin":
            self._json(403, {"error": "admin role required"})
            return None
        return user

    def _session_cookie(self, token, max_age):
        return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={max_age}"

    def _json(self, status, payload, cookie=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, page):
        data = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc.lower() != self.headers.get("Host", "").lower() or parsed.scheme not in {"http", "https"}:
                self._json(403, {"error": "cross-origin request blocked"})
                return False
        return True

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_POST_BYTES:
            self._json(413, {"error": "request body too large"})
            return None
        if "application/json" not in self.headers.get("Content-Type", ""):
            self._json(415, {"error": "expected application/json"})
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self._json(400, {"error": "invalid JSON body"})
            return None
        return payload

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in {"/", "/login"}:
            signed_in = dashboard_auth.session_user(self._token()) is not None
            if path == "/":
                self._html(PAGE) if signed_in else self._redirect("/login")
            else:
                self._redirect("/") if signed_in else self._html(LOGIN_PAGE)
            return
        if path == "/api/me":
            user = self._require(allow_pending=True)
            if user:
                self._json(200, user)
            return
        if not self._require(admin=path in {"/api/users", "/api/adoption/config"}):
            return
        if path == "/api/status":
            self._json(200, dashboard_status())
        elif path == "/api/discoveries":
            self._json(200, dashboard_discoveries())
        elif path == "/api/users":
            self._json(200, {"users": dashboard_auth.list_users()})
        elif path == "/api/adoptions":
            self._json(200, {"adoptions": adopt.list_adoptions(), "projects": adopt.projects()})
        elif path == "/api/adoption/config":
            self._json(200, {"providers": adopt.provider_status(), "github": adopt.github_identity(),
                             "projects": adopt.projects(), "max_cost_usd": adopt.MAX_COST_PER_ADOPTION_USD})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in POST_ROUTES:
            self._json(404, {"error": "not found"})
            return
        if not self._same_origin():
            return
        if path == "/api/login":
            self._login()
        elif path == "/api/logout":
            dashboard_auth.end_session(self._token())
            self._json(200, {"ok": True}, cookie=self._session_cookie("", 0))
        elif path == "/api/password":
            self._change_password()
        elif path.startswith("/api/users/"):
            self._users_action(path)
        elif path in ADOPTION_ROUTES:
            self._adoption_action(path)
        elif self._require():
            self._triage() if path == "/api/triage" else self._run()

    def _login(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            user = dashboard_auth.authenticate(payload.get("username"), payload.get("password"), self._client())
        except dashboard_auth.AuthError as exc:
            self._json(401, {"error": str(exc)})
            return
        token = dashboard_auth.create_session(user["username"])
        self._json(200, user, cookie=self._session_cookie(token, dashboard_auth.SESSION_MAX_SECONDS))

    def _change_password(self):
        user = self._require(allow_pending=True)
        payload = self._read_json_body() if user else None
        if payload is None:
            return
        try:
            dashboard_auth.change_password(user["username"], payload.get("current"), payload.get("new"))
        except dashboard_auth.AuthError as exc:
            self._json(400, {"error": str(exc)})
            return
        except OSError:
            self._json(500, {"error": "Não foi possível salvar a nova senha."})
            return
        dashboard_auth.revoke_sessions(user["username"], keep=self._token())
        self._json(200, {"ok": True})

    def _users_action(self, path):
        admin = self._require(admin=True)
        payload = self._read_json_body() if admin else None
        if payload is None:
            return
        username = payload.get("username")
        actor = admin["username"]
        try:
            if path == "/api/users/create":
                password = dashboard_auth.create_user(username, payload.get("role"), actor)
                self._json(201, {"username": str(username).strip().lower(), "password": password})
            elif path == "/api/users/reset":
                self._json(200, {"username": username, "password": dashboard_auth.reset_password(username, actor)})
            elif path == "/api/users/role":
                if username == actor:
                    raise dashboard_auth.AuthError("Você não pode mudar o próprio papel.")
                dashboard_auth.set_role(username, payload.get("role"), actor)
                self._json(200, {"ok": True})
            else:
                dashboard_auth.delete_user(username, actor)
                self._json(200, {"ok": True})
        except dashboard_auth.AuthError as exc:
            self._json(400, {"error": str(exc)})
        except OSError:
            self._json(500, {"error": "Não foi possível salvar o cadastro de usuários."})

    def _adoption_action(self, path):
        admin = self._require(admin=True)
        payload = self._read_json_body() if admin else None
        if payload is None:
            return
        actor = admin["username"]
        try:
            if path == "/api/translate":
                translate.trigger()
                result = {"started": True}
            elif path == "/api/adoption/settings":
                adopt.save_settings(payload.get("provider"), payload.get("model"), actor)
                translate.trigger()
                result = {"ok": True}
            elif path == "/api/projects/add":
                result = adopt.add_project(payload.get("repo"), actor)
            elif path == "/api/projects/remove":
                adopt.remove_project(payload.get("repo"), actor)
                result = {"ok": True}
            elif path == "/api/adoptions/preview":
                repos = payload.get("repos") if isinstance(payload.get("repos"), list) else []
                result = adopt.start_preview(payload.get("source"), payload.get("note"), repos, actor)
            elif path == "/api/adoptions/deploy":
                result = adopt.deploy(payload.get("id"), actor)
            elif path == "/api/adoptions/discard":
                adopt.discard(payload.get("id"), actor)
                result = {"ok": True}
            else:
                result = adopt.revert(payload.get("id"), payload.get("repo"), actor)
        except adopt.AdoptionError as exc:
            self._json(400, {"error": str(exc)})
            return
        except OSError:
            self._json(500, {"error": "Não foi possível salvar a operação."})
            return
        self._json(200, result)

    def _triage(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            saved = set_triage(payload.get("source"), payload.get("state"))
        except ValueError:
            self._json(400, {"error": "invalid triage request"})
            return
        except OSError:
            self._json(500, {"error": "triage could not be saved"})
            return
        if not saved:
            self._json(404, {"error": "discovery not found"})
            return
        self._json(200, {"saved": True})

    def _run(self):
        try:
            started = start_research()
        except OSError:
            self._json(500, {"error": "research process could not be started"})
            return
        if not started:
            self._json(409, {"error": "research is already running"})
            return
        self._json(202, {"started": True})


def main():
    if sys.argv[1:2] == ["users"]:
        sys.exit(dashboard_auth.cli(sys.argv[2:]))
    if not PASSWORD or len(PASSWORD) < 24:
        raise SystemExit("Set AES_DASHBOARD_PASSWORD to a strong password of at least 24 characters.")
    if not USERNAME or ":" in USERNAME:
        raise SystemExit("Set AES_DASHBOARD_USER to a non-empty username without colons.")
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    server.daemon_threads = True
    translate.start_background()
    server.serve_forever()


if __name__ == "__main__":
    main()
