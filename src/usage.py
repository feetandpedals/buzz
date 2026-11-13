"""Who owns which reel, whose Claude key pays, and how much has been used.
- Every reel has an owner (the signed-in user who made it). Members see only their own reels; the owner (admin) sees all.
- Every user can add their own Claude key (stored under anthropic:<email>); work done with it costs the user, not the studio.
- Work done with the shared studio key is counted per user and can be limited (monthly tokens, reels per day), paused for
  everyone with a kill switch, and capped by a studio-wide monthly budget. Settings live in Work/policy.json, usage in
  Work/usage.jsonl (one line per Claude call; tokens only, never prompts or keys)."""
import json
import time
from pathlib import Path

import secrets_store as vault

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "Work"
POLICY = WORK / "policy.json"
LOG = WORK / "usage.jsonl"
SERVICE = "ai-reel-studio"
_ctx = {"user": "", "reel": ""}

DEFAULTS = {"kill": False, "global_monthly_tokens": 0, "price_in_per_m": 0.0, "price_out_per_m": 0.0,
            "default": {"monthly_tokens": 0, "daily_reels": 0, "shared_key": False}, "users": {}}


class LimitError(RuntimeError):
    """A limit or missing key stopped the request; the message is written for the user."""


def norm(email):
    return (email or "").strip().lower()


# ---------------------------------------------------------------- policy
def policy():
    try:
        p = json.loads(POLICY.read_text(encoding="utf-8"))
    except Exception:
        p = {}
    out = json.loads(json.dumps(DEFAULTS))
    out.update({k: v for k, v in p.items() if k in out and k not in ("default", "users")})
    out["default"].update(p.get("default", {}))
    out["users"] = p.get("users", {})
    return out


def save_policy(p):
    WORK.mkdir(parents=True, exist_ok=True)
    POLICY.write_text(json.dumps(p, indent=1), encoding="utf-8")


def user_policy(email, is_owner=False):
    p = policy()
    u = dict(p["default"])
    u.update(p["users"].get(norm(email), {}))
    if is_owner:
        u["shared_key"] = True
    return u


# ---------------------------------------------------------------- context (set by the worker for the job in hand)
def set_context(user="", reel=""):
    _ctx["user"], _ctx["reel"] = norm(user), reel


def context():
    return dict(_ctx)


# ---------------------------------------------------------------- ownership
def owner_of(name):
    """Owner of a reel by folder name; '' for reels made before accounts were tracked (visible to the admin only)."""
    f = WORK / "jobs" / name / "owner.txt"
    if f.exists():
        return norm(f.read_text(encoding="utf-8"))
    o = ROOT / "Reels In" / name / "options.json"
    if o.exists():
        try:
            return norm(json.loads(o.read_text(encoding="utf-8-sig")).get("owner", ""))
        except Exception:
            return ""
    return ""


def record_owner(name, email):
    f = WORK / "jobs" / name / "owner.txt"
    if email and not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(norm(email), encoding="utf-8")


def can_see(name, email, is_owner):
    return is_owner or (bool(email) and owner_of(name) == norm(email))


# ---------------------------------------------------------------- usage log
def _rows():
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def record(user, reel, op, model, usage, source):
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "user": norm(user), "reel": reel, "op": op, "model": model,
           "in": int((usage or {}).get("input_tokens") or 0), "out": int((usage or {}).get("output_tokens") or 0), "key": source}
    WORK.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def record_reel_start(user, reel):
    record(user, reel, "reel_start", "", {}, "")


def month_key(ts=None):
    return (ts or time.strftime("%Y-%m-%d %H:%M:%S"))[:7]


def tokens(rows):
    return sum(r.get("in", 0) + r.get("out", 0) for r in rows)


def stats(email):
    """This month's numbers for one user: shared-key tokens, own-key tokens, reels started this month and today."""
    m, d = month_key(), time.strftime("%Y-%m-%d")
    mine = [r for r in _rows() if r.get("user") == norm(email) and r.get("ts", "")[:7] == m]
    calls = [r for r in mine if r.get("op") != "reel_start"]
    starts = [r for r in mine if r.get("op") == "reel_start"]
    return {"shared_tokens": tokens([r for r in calls if r.get("key") == "shared"]),
            "own_tokens": tokens([r for r in calls if r.get("key") == "own"]),
            "reels_month": len(starts), "reels_today": len([r for r in starts if r["ts"][:10] == d])}


def studio_shared_tokens_month():
    m = month_key()
    return tokens([r for r in _rows() if r.get("key") == "shared" and r.get("ts", "")[:7] == m])


def cost_estimate(in_tokens, out_tokens):
    p = policy()
    if not (p["price_in_per_m"] or p["price_out_per_m"]):
        return None
    return in_tokens / 1e6 * p["price_in_per_m"] + out_tokens / 1e6 * p["price_out_per_m"]


def month_in_out(email=None):
    m = month_key()
    rows = [r for r in _rows() if r.get("ts", "")[:7] == m and r.get("key") == "shared" and (email is None or r.get("user") == norm(email))]
    return sum(r.get("in", 0) for r in rows), sum(r.get("out", 0) for r in rows)


# ---------------------------------------------------------------- which key, and may it be used
def own_entry(email):
    return "anthropic:" + norm(email)


def has_own_key(email):
    return bool(email) and bool(vault.get_password(SERVICE, own_entry(email)))


def _is_admin(email):
    try:
        import auth
        return auth.role_of(email) == "owner"
    except Exception:
        return False


def key_for(email):
    """(key, 'own' | 'shared') for this user, or raises LimitError with a plain message."""
    email = norm(email)
    if not email:  # no user context (legacy jobs, command line): the studio key, as before
        k = vault.get_password(SERVICE, "anthropic")
        if not k:
            raise LimitError("No Claude key saved. Add it on the Settings tab.")
        return k, "shared"
    if has_own_key(email):
        return vault.get_password(SERVICE, own_entry(email)), "own"
    up = user_policy(email, _is_admin(email))
    if not up["shared_key"]:
        raise LimitError("Add your own Claude key on the Settings tab to make reels. The administrator can also allow you to use the shared key.")
    k = vault.get_password(SERVICE, "anthropic")
    if not k:
        raise LimitError("The studio has no Claude key saved yet. Ask the administrator.")
    return k, "shared"


def check_before_call(email, source):
    """Raises LimitError if this call must not go ahead. Only shared-key use is limited; a user's own key is their own spend."""
    if source != "shared":
        return
    p = policy()
    if p["kill"]:
        raise LimitError("AI use is paused by the administrator. Please try again later.")
    if p["global_monthly_tokens"] and studio_shared_tokens_month() >= p["global_monthly_tokens"]:
        raise LimitError("The studio's monthly AI budget is used up. Add your own Claude key on the Settings tab, or ask the administrator.")
    email = norm(email)
    if email:
        up = user_policy(email, _is_admin(email))
        if up["monthly_tokens"] and stats(email)["shared_tokens"] >= up["monthly_tokens"]:
            raise LimitError("Your monthly allowance on the shared key is used up. Add your own Claude key on the Settings tab, or ask the administrator.")


def check_reel_start(email):
    """Called when a reel begins: key available, kill switch, daily reel cap."""
    email = norm(email)
    key, source = key_for(email)
    check_before_call(email, source)
    if email:
        up = user_policy(email, _is_admin(email))
        if up["daily_reels"] and stats(email)["reels_today"] >= up["daily_reels"]:
            raise LimitError(f"You have reached today's limit of {up['daily_reels']} reels. Please try again tomorrow.")
    return source


def can_make_reels(email):
    """(ok, message) for the Create tab banner."""
    try:
        key_for(email)
        return True, ""
    except LimitError as e:
        return False, str(e)
