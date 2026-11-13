"""Accounts for the web page: email + password, a first-time setup, and password resets with a 6-digit code.
Passwords are stored only as salted scrypt hashes in Work/users.json (never the password itself).
A reset code is sent by email when the optional mail slot is set up (mailer.py); otherwise the studio owner
creates the code in Settings and passes it on. Codes live 15 minutes, work once, and only their hash is stored."""
import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USERS = ROOT / "Work" / "users.json"
RESETS = ROOT / "Work" / "resets.json"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE_LIFE = 15 * 60
MIN_LEN = 8


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")


def norm(email):
    return (email or "").strip().lower()


def _hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return salt.hex() + ":" + h.hex()


def _same(password, stored):
    try:
        salt, h = stored.split(":")
        return hmac.compare_digest(_hash(password, bytes.fromhex(salt)).split(":")[1], h)
    except Exception:
        return False


def has_users():
    return bool(_load(USERS))


def check_password_rules(password):
    if len(password or "") < MIN_LEN:
        return f"Please use at least {MIN_LEN} characters."
    return None


def create_user(email, password, role="member"):
    """Returns an error text, or None when the account was made."""
    email = norm(email)
    if not EMAIL_RE.match(email):
        return "That does not look like an email address."
    err = check_password_rules(password)
    if err:
        return err
    users = _load(USERS)
    if email in users:
        return "There is already an account with that email."
    users[email] = {"hash": _hash(password), "role": role, "created": time.strftime("%Y-%m-%d %H:%M")}
    _save(USERS, users)
    return None


def verify(email, password):
    """Returns the user's role when email and password match, else None. Takes the same time either way."""
    users = _load(USERS)
    u = users.get(norm(email))
    ok = _same(password or "", u["hash"] if u else _hash("not-a-real-password"))
    return u["role"] if (u and ok) else None


def role_of(email):
    return _load(USERS).get(norm(email), {}).get("role")


def list_users():
    return {e: u["role"] for e, u in _load(USERS).items()}


def remove_user(email):
    users = _load(USERS)
    if users.get(norm(email), {}).get("role") == "owner":
        return "The owner account cannot be removed."
    users.pop(norm(email), None)
    _save(USERS, users)
    end_all_sessions(email)
    return None


def set_password(email, password):
    err = check_password_rules(password)
    if err:
        return err
    users = _load(USERS)
    if norm(email) not in users:
        return "No such account."
    users[norm(email)]["hash"] = _hash(password)
    _save(USERS, users)
    end_all_sessions(email)  # a new password signs the account out on every browser
    return None


# ---------------------------------------------------------------- "keep me signed in" (30 days, same browser)
SESSIONS = ROOT / "Work" / "sessions.json"
SESSION_DAYS = 30


def _tok_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(email):
    """Returns a random token for the browser cookie. Only its hash is kept here."""
    sess = {k: v for k, v in _load(SESSIONS).items() if v.get("expires", 0) > time.time()}  # drop old ones
    token = secrets.token_urlsafe(32)
    sess[_tok_hash(token)] = {"email": norm(email), "expires": time.time() + SESSION_DAYS * 86400}
    _save(SESSIONS, sess)
    return token


def session_user(token):
    """(email, role) for a valid, unexpired token whose account still exists, else None."""
    if not isinstance(token, str) or not token or len(token) > 100:
        return None
    s = _load(SESSIONS).get(_tok_hash(token))
    if not s or s.get("expires", 0) < time.time():
        return None
    u = _load(USERS).get(s["email"])
    return (s["email"], u["role"]) if u else None


def end_session(token):
    if not token:
        return
    sess = _load(SESSIONS)
    if sess.pop(_tok_hash(token), None) is not None:
        _save(SESSIONS, sess)


def end_all_sessions(email):
    """Signs an account out everywhere (used when its password changes or it is removed)."""
    sess = {k: v for k, v in _load(SESSIONS).items() if v.get("email") != norm(email)}
    _save(SESSIONS, sess)


# ---------------------------------------------------------------- password resets
def _new_code():
    return f"{secrets.randbelow(10 ** 6):06d}"


def issue_code(email):
    """Creates a one-time code for an existing account. Returns the code, or None when there is no such account."""
    email = norm(email)
    if email not in _load(USERS):
        return None
    code = _new_code()
    res = _load(RESETS)
    res[email] = {"hash": _hash(code), "expires": time.time() + CODE_LIFE, "tries": 0, "requested": time.time(),
                  "issued": True}
    _save(RESETS, res)
    return code


def request_reset(email):
    """Someone pressed 'Forgot password'. Records the request (no code yet) so the owner can see it.
    Always returns quietly: the page never reveals whether an email has an account."""
    email = norm(email)
    if email in _load(USERS):
        res = _load(RESETS)
        res.setdefault(email, {})
        res[email].update(requested=time.time(), issued=res[email].get("issued", False) and
                          res[email].get("expires", 0) > time.time())
        _save(RESETS, res)


def pending_requests():
    """Emails that asked for a reset in the last day and have no live code yet (for the owner to see)."""
    now, out = time.time(), []
    for email, r in _load(RESETS).items():
        if now - r.get("requested", 0) < 86400 and not (r.get("issued") and r.get("expires", 0) > now):
            out.append(email)
    return out


def finish_reset(email, code, new_password):
    """Returns an error text, or None when the password was changed."""
    email = norm(email)
    res = _load(RESETS)
    r = res.get(email)
    if not r or not r.get("issued") or r.get("expires", 0) < time.time():
        return "That code has expired or was not issued. Ask for a new one."
    if r.get("tries", 0) >= 5:
        res.pop(email, None)
        _save(RESETS, res)
        return "Too many wrong codes. Please ask for a new one."
    if not _same((code or "").strip(), r["hash"]):
        r["tries"] = r.get("tries", 0) + 1
        _save(RESETS, res)
        return "That code is not right. Please check it and try again."
    err = set_password(email, new_password)
    if err:
        return err
    res.pop(email, None)
    _save(RESETS, res)
    return None
