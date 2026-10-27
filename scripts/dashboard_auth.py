"""Users, password hashing, sessions, and login throttling for the AES dashboard; stdlib only.

The account from AES_DASHBOARD_USER/AES_DASHBOARD_PASSWORD is a built-in recovery admin: it always
works, cannot be edited from the UI, and is how an operator regains access if every other admin
password is lost. Additional accounts live in <state>/private/dashboard-users.json as PBKDF2 hashes.
"""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

import innovation

PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 12
SESSION_IDLE_SECONDS = 12 * 3600
SESSION_MAX_SECONDS = 7 * 24 * 3600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300
ROLES = {"admin", "member"}
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")

_users_lock = threading.Lock()
_sessions_lock = threading.Lock()
_sessions = {}
_failures = {}
# Spend the same hashing time for unknown users so response time does not reveal which names exist.
_DUMMY_HASH = None


class AuthError(ValueError):
    """A user-facing validation error; the message is safe to show."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def users_path():
    return innovation.STATE / "private" / "dashboard-users.json"


def audit_path():
    return innovation.STATE / "private" / "dashboard-audit.jsonl"


def builtin_username():
    return os.environ.get("AES_DASHBOARD_USER", "aes")


def builtin_password():
    return os.environ.get("AES_DASHBOARD_PASSWORD", "")


def hash_password(password, iterations=None):
    iterations = iterations or PBKDF2_ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    encode = lambda raw: base64.b64encode(raw).decode("ascii")
    return f"pbkdf2_sha256${iterations}${encode(salt)}${encode(digest)}"


def verify_password(password, stored):
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def _dummy_hash():
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    return _DUMMY_HASH


def temporary_password():
    return secrets.token_urlsafe(15)


def validate_new_password(password, username):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    if len(password) > 256:
        raise AuthError("A senha é longa demais.")
    if password.strip().lower() == username.lower():
        raise AuthError("A senha não pode ser igual ao nome de usuário.")


def audit(event, actor, target=None):
    path = audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        row = {"time": _now(), "event": event, "actor": actor}
        if target:
            row["target"] = target
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if os.name != "nt":
            path.chmod(0o600)
    except OSError:
        pass


def load_users():
    try:
        data = json.loads(users_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    users = data.get("users") if isinstance(data, dict) else None
    return {name: row for name, row in (users or {}).items() if isinstance(row, dict) and row.get("password")}


def _save_users(users):
    path = users_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"version": 1, "users": users}, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        temp.chmod(0o600)
    os.replace(temp, path)


def public_user(name, row):
    return {"username": name, "role": row.get("role", "member"), "created_at": row.get("created_at"),
            "last_login": row.get("last_login"), "must_change": bool(row.get("must_change")), "builtin": False}


def list_users():
    rows = [{"username": builtin_username(), "role": "admin", "created_at": None, "last_login": None,
             "must_change": False, "builtin": True}]
    rows.extend(public_user(name, row) for name, row in sorted(load_users().items()))
    return rows


def _check_username(username):
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        raise AuthError("Use de 2 a 32 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado.")
    if username == builtin_username():
        raise AuthError("Esse nome pertence à conta de recuperação definida no servidor.")


def create_user(username, role, actor):
    username = (username or "").strip().lower()
    _check_username(username)
    if role not in ROLES:
        raise AuthError("Papel inválido.")
    password = temporary_password()
    with _users_lock:
        users = load_users()
        if username in users:
            raise AuthError("Já existe um usuário com esse nome.")
        users[username] = {"password": hash_password(password), "role": role, "created_at": _now(),
                           "created_by": actor, "must_change": True}
        _save_users(users)
    audit("user_created", actor, username)
    return password


def reset_password(username, actor):
    password = temporary_password()
    with _users_lock:
        users = load_users()
        if username not in users:
            raise AuthError("Usuário não encontrado.")
        users[username].update(password=hash_password(password), must_change=True, reset_at=_now())
        _save_users(users)
    revoke_sessions(username)
    _failures.pop(username, None)
    audit("password_reset", actor, username)
    return password


def set_role(username, role, actor):
    if role not in ROLES:
        raise AuthError("Papel inválido.")
    with _users_lock:
        users = load_users()
        if username not in users:
            raise AuthError("Usuário não encontrado.")
        users[username]["role"] = role
        _save_users(users)
    audit("role_changed", actor, f"{username}:{role}")


def delete_user(username, actor):
    if username == actor:
        raise AuthError("Você não pode excluir a própria conta.")
    with _users_lock:
        users = load_users()
        if username not in users:
            raise AuthError("Usuário não encontrado.")
        del users[username]
        _save_users(users)
    revoke_sessions(username)
    audit("user_deleted", actor, username)


def change_password(username, current, new):
    if username == builtin_username():
        raise AuthError("A senha da conta de recuperação é definida na variável AES_DASHBOARD_PASSWORD do servidor.")
    validate_new_password(new, username)
    with _users_lock:
        users = load_users()
        row = users.get(username)
        if not row or not verify_password(current or "", row["password"]):
            raise AuthError("A senha atual está incorreta.")
        if verify_password(new, row["password"]):
            raise AuthError("A nova senha precisa ser diferente da atual.")
        row.update(password=hash_password(new), must_change=False, changed_at=_now())
        _save_users(users)
    audit("password_changed", username, username)


def _locked(key):
    entry = _failures.get(key)
    return bool(entry and entry[0] >= MAX_FAILURES and time.monotonic() - entry[1] < LOCKOUT_SECONDS)


def _fail(key):
    count, first = _failures.get(key, (0, time.monotonic()))
    if time.monotonic() - first >= LOCKOUT_SECONDS:
        count, first = 0, time.monotonic()
    _failures[key] = (count + 1, first if count else time.monotonic())


def authenticate(username, password, client):
    """Return the user dict on success. Raises AuthError with a generic message on failure."""
    username = (username or "").strip().lower() if username != builtin_username() else username
    if not isinstance(password, str) or not username:
        raise AuthError("Usuário ou senha incorretos.")
    keys = (f"user:{username}", f"client:{client}")
    if any(_locked(key) for key in keys):
        raise AuthError("Muitas tentativas. Aguarde alguns minutos e tente de novo.")
    user = None
    expected = builtin_password()
    if username == builtin_username() and expected:
        if hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8")):
            user = {"username": username, "role": "admin", "must_change": False, "builtin": True}
        verify_password(password, _dummy_hash())
    else:
        row = load_users().get(username)
        if row and verify_password(password, row["password"]):
            user = public_user(username, row)
        elif not row:
            verify_password(password, _dummy_hash())
    if not user:
        for key in keys:
            _fail(key)
        audit("login_failed", username if username in load_users() or username == builtin_username() else "unknown")
        raise AuthError("Usuário ou senha incorretos.")
    for key in keys:
        _failures.pop(key, None)
    if not user["builtin"]:
        with _users_lock:
            users = load_users()
            if username in users:
                users[username]["last_login"] = _now()
                _save_users(users)
    audit("login", username)
    return user


def create_session(username):
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _sessions_lock:
        _sessions[token] = {"username": username, "created": now, "seen": now}
    return token


def session_user(token):
    """Resolve a session token to the current user, or None. Re-reads the store so role changes apply."""
    if not token:
        return None
    now = time.monotonic()
    with _sessions_lock:
        session = _sessions.get(token)
        if not session:
            return None
        if now - session["seen"] > SESSION_IDLE_SECONDS or now - session["created"] > SESSION_MAX_SECONDS:
            del _sessions[token]
            return None
        session["seen"] = now
        username = session["username"]
    if username == builtin_username() and builtin_password():
        return {"username": username, "role": "admin", "must_change": False, "builtin": True}
    row = load_users().get(username)
    if not row:
        end_session(token)
        return None
    return public_user(username, row)


def end_session(token):
    with _sessions_lock:
        _sessions.pop(token, None)


def revoke_sessions(username, keep=None):
    with _sessions_lock:
        for token in [t for t, s in _sessions.items() if s["username"] == username and t != keep]:
            del _sessions[token]


def cli(argv):
    """Operator commands for the container shell: list, add, reset, delete."""
    import argparse
    parser = argparse.ArgumentParser(prog="dashboard.py users", description="Manage AES dashboard users.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="List users")
    add = sub.add_parser("add", help="Create a user and print a temporary password")
    add.add_argument("username")
    add.add_argument("--admin", action="store_true", help="Grant the admin role")
    reset = sub.add_parser("reset", help="Reset a password and print a temporary one")
    reset.add_argument("username")
    remove = sub.add_parser("delete", help="Delete a user")
    remove.add_argument("username")
    args = parser.parse_args(argv)
    try:
        if args.action == "list":
            for user in list_users():
                flag = " (recuperação)" if user["builtin"] else " (troca pendente)" if user["must_change"] else ""
                print(f"{user['username']:<32} {user['role']:<7}{flag}")
        elif args.action == "add":
            password = create_user(args.username, "admin" if args.admin else "member", "cli")
            print(f"Usuário criado. Senha temporária (troca obrigatória no primeiro acesso): {password}")
        elif args.action == "reset":
            password = reset_password(args.username, "cli")
            print(f"Senha redefinida. Senha temporária (troca obrigatória no próximo acesso): {password}")
        else:
            delete_user(args.username, "cli")
            print("Usuário excluído.")
    except AuthError as exc:
        print(str(exc))
        return 2
    return 0
