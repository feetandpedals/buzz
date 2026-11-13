"""Tests for per-user reels, keys, usage and limits. Run from the Buzz folder:  python tests/test_per_user.py
Uses a throw-away Work folder inside this copy and an in-memory key store (nothing touches real keys)."""
import io
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))
work = root / "Work"
assert not (work / "users.json").exists() or "--force" in sys.argv, "Work/users.json exists; refusing to touch a real install"


class FakeVault:
    WHERE = "test store"
    d = {}
    def get_password(self, s, n): return self.d.get((s, n))
    def set_password(self, s, n, v): self.d[(s, n)] = v
    def delete_password(self, s, n): self.d.pop((s, n), None)


import usage, auth, claude_api  # noqa: E402
usage.vault = FakeVault()
V = usage.vault
fails = []


def check(label, cond):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        fails.append(label)


def raises(fn, text=None):
    try:
        fn()
    except usage.LimitError as e:
        return (text is None) or (text in str(e))
    except Exception:
        return False
    return False


try:
    work.mkdir(exist_ok=True)
    auth.create_user("boss@x.com", "password123", "owner")
    auth.create_user("ann@x.com", "password123", "member")
    auth.create_user("bob@x.com", "password123", "member")

    # ---- which key
    V.set_password("ai-reel-studio", "anthropic", "SHARED-KEY")
    check("member with no own key and no permission is refused", raises(lambda: usage.key_for("ann@x.com"), "own Claude key"))
    check("owner uses the shared key", usage.key_for("boss@x.com") == ("SHARED-KEY", "shared"))
    p = usage.policy(); p["users"]["ann@x.com"] = {"shared_key": True, "monthly_tokens": 1000, "daily_reels": 2}; usage.save_policy(p)
    check("permitted member gets the shared key", usage.key_for("ann@x.com") == ("SHARED-KEY", "shared"))
    V.set_password("ai-reel-studio", usage.own_entry("bob@x.com"), "BOB-OWN")
    check("a member's own key wins and is marked own", usage.key_for("bob@x.com") == ("BOB-OWN", "own"))
    check("no user context (legacy job) keeps using the studio key", usage.key_for("") == ("SHARED-KEY", "shared"))

    # ---- usage recording through the client hook, with the network faked
    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake_urlopen(req, timeout=0):
        return Resp(json.dumps({"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn", "usage": {"input_tokens": 400, "output_tokens": 200}}).encode())
    orig = urllib.request.urlopen; urllib.request.urlopen = fake_urlopen
    usage.set_context("ann@x.com", "Reel A")
    import secrets_store; secrets_store.get_password = V.get_password
    c = claude_api.Client("SHARED-KEY", before=lambda: usage.check_before_call("ann@x.com", "shared"),
                          on_usage=lambda m, u: usage.record("ann@x.com", "Reel A", "claude", m, u, "shared"))
    r = c.messages.create("m", 10, [{"role": "user", "content": "x"}])
    urllib.request.urlopen = orig
    check("client returns the reply text", r.content[0].text == "hi")
    s = usage.stats("ann@x.com")
    check("tokens were recorded against the right user as shared", s["shared_tokens"] == 600 and s["own_tokens"] == 0)

    # ---- limits
    check("under the monthly allowance a call may go ahead", not raises(lambda: usage.check_before_call("ann@x.com", "shared")))
    usage.record("ann@x.com", "Reel A", "claude", "m", {"input_tokens": 300, "output_tokens": 200}, "shared")
    check("over the monthly allowance the shared key is refused", raises(lambda: usage.check_before_call("ann@x.com", "shared"), "allowance"))
    check("own-key use is never limited", not raises(lambda: usage.check_before_call("ann@x.com", "own")))
    p = usage.policy(); p["kill"] = True; usage.save_policy(p)
    check("emergency stop refuses shared-key calls", raises(lambda: usage.check_before_call("boss@x.com", "shared"), "paused"))
    check("emergency stop does not touch own keys", not raises(lambda: usage.check_before_call("bob@x.com", "own")))
    p["kill"] = False; p["global_monthly_tokens"] = 100; usage.save_policy(p)
    check("studio monthly budget stops everyone on the shared key", raises(lambda: usage.check_before_call("boss@x.com", "shared"), "budget"))
    p["global_monthly_tokens"] = 0; p["users"]["ann@x.com"]["monthly_tokens"] = 0; usage.save_policy(p)
    usage.record_reel_start("ann@x.com", "Reel A"); usage.record_reel_start("ann@x.com", "Reel B")
    check("daily reel limit stops the third reel", raises(lambda: usage.check_reel_start("ann@x.com"), "limit of 2"))
    check("owner is not subject to the daily limit", not raises(lambda: usage.check_reel_start("boss@x.com")))
    check("cost estimate is blank until prices are set", usage.cost_estimate(1000, 1000) is None)
    p["price_in_per_m"], p["price_out_per_m"] = 3.0, 15.0; usage.save_policy(p)
    check("cost estimate uses the prices", abs(usage.cost_estimate(1_000_000, 1_000_000) - 18.0) < 1e-9)

    # ---- reel ownership
    for name, owner in (("Reel A", "ann@x.com"), ("Reel B", "bob@x.com"), ("Old reel", "")):
        d = work / "jobs" / name; d.mkdir(parents=True, exist_ok=True)
        (d / "job.json").write_text(json.dumps({"status": "done", "seconds": 10}))
        if owner:
            usage.record_owner(name, owner)
    check("member sees only own reel", usage.can_see("Reel A", "ann@x.com", False) and not usage.can_see("Reel B", "ann@x.com", False))
    check("member does not see unowned old reels", not usage.can_see("Old reel", "ann@x.com", False))
    check("owner sees everything", all(usage.can_see(n, "boss@x.com", True) for n in ("Reel A", "Reel B", "Old reel")))

    # ---- the pages
    from streamlit.testing.v1 import AppTest
    def page(tab, email, role):
        pre = ('st.session_state.setdefault("signed_in", True); st.session_state.setdefault("user_email", "%s"); '
               'st.session_state.setdefault("user_role", "%s"); st.session_state.setdefault("tab_cur", "%s")\n' % (email, role, tab))
        s = (root / "src" / "app.py").read_text(encoding="utf-8").replace("st.set_page_config(", pre + "st.set_page_config(", 1)
        s = s.replace("        return ui.tabs(options, value=value, key=key)", "        raise RuntimeError('fallback')")
        f = root / "src" / "_pu_test.py"; f.write_text(s, encoding="utf-8")
        at = AppTest.from_file(str(f), default_timeout=90); at.run()
        return at, f
    def text(at):
        return " ".join(str(x.value) for x in list(at.markdown) + list(at.caption) + list(at.warning) + list(at.success))
    at, f = page("My reels", "ann@x.com", "member")
    t = text(at)
    check("Ann's My reels shows Reel A only", "Reel A" in t and "Reel B" not in t and "Old reel" not in t and not at.exception)
    at, f = page("My reels", "boss@x.com", "owner")
    t = text(at)
    check("owner's My reels shows all three with owners", all(n in t for n in ("Reel A", "Reel B", "Old reel")) and "ann@x.com" in t)
    at, f = page("Settings", "bob@x.com", "member")
    t = text(at)
    check("member Settings has own-key card, no people or shared controls", "Your Claude key" in t and "Usage and limits" not in t and "People" not in t and not at.exception)
    at, f = page("Settings", "boss@x.com", "owner")
    t = text(at)
    check("owner Settings shows usage and limits", "Usage and limits" in t and not at.exception)
    [b for b in at.button if b.key == "u_save"][0].click(); at.run()
    check("owner can save limits", "Limits saved." in text(at))
    # a member without permission sees the banner on Create
    V.d.pop(("ai-reel-studio", usage.own_entry("bob@x.com")), None)
    at, f = page("Create", "bob@x.com", "member")
    check("member without key or permission sees the 'one step left' banner", "One step left" in text(at))
    f.unlink(missing_ok=True)
finally:
    shutil.rmtree(work, ignore_errors=True)
    for p in ("_pu_test.py",):
        (root / "src" / p).unlink(missing_ok=True)
print()
print("ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
