"""Buzz web page. The background worker does the real work and never depends on this page."""
import hmac
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import keyring
import streamlit as st
import streamlit_shadcn_ui as ui  # MIT licensed shadcn components for Streamlit

ROOT = Path(__file__).resolve().parent.parent
WORK, REELS_IN, REELS_OUT = ROOT / "Work", ROOT / "Reels In", ROOT / "Reels Out"
TASK = "Buzz Worker"
SERVICE = "ai-reel-studio"
try:  # the address of this page on your own devices (Tailscale); kept in a small file, not in the code
    PUBLIC_URL = (WORK / "public_url.txt").read_text(encoding="utf-8").strip()
except OSError:
    PUBLIC_URL = ""
try:
    from common import HISTORY_DAYS
except Exception:
    HISTORY_DAYS = 15
AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

st.set_page_config(page_title="Buzz: AI Reel Studio", page_icon="🎬", layout="centered")


def footer():
    st.markdown('<div style="text-align:center;opacity:.65;font-size:.82rem;margin:2.5rem 0 1rem">Built by Amit at '
                '<a href="https://nobrand.in" target="_blank" rel="noopener">https://nobrand.in</a> - collaborator '
                '<a href="https://feetandpedals.com" target="_blank" rel="noopener">feetandpedals.com</a></div>', unsafe_allow_html=True)


CSS = """
<style>
header[data-testid="stHeader"], #MainMenu, footer {display:none !important;}
.block-container {max-width: 940px; padding: 1.1rem 1rem 4rem 1rem;}
.rs-hero {background: linear-gradient(135deg,#18181b 0%,#27272a 55%,#7c2d12 130%); color:#fff; border-radius:18px;
  padding:20px 24px; display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap;
  margin-bottom:14px;}
.rs-hero h1 {margin:0; font-size:1.7rem; font-weight:800; letter-spacing:-0.02em; color:#fff; padding:0;}
.rs-hero p {margin:4px 0 0 0; color:#d4d4d8; font-size:.95rem;}
.rs-pill {display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:4px 12px; font-size:.82rem;
  font-weight:600; white-space:nowrap;}
.rs-green {background:#dcfce7; color:#166534;} .rs-red {background:#fee2e2; color:#991b1b;}
.rs-amber {background:#fef3c7; color:#92400e;} .rs-gray {background:#f4f4f5; color:#3f3f46;}
.rs-steps {display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:10px 0 14px 0;}
.rs-step {border:1px solid #e4e4e7; border-radius:14px; padding:12px 14px; background:#fafafa;}
.rs-step b {display:block; font-size:.95rem; margin-bottom:2px;}
.rs-step span {color:#52525b; font-size:.85rem;}
.rs-step .rs-num {display:inline-flex; width:22px; height:22px; border-radius:50%; background:#18181b;
  color:#fff !important; align-items:center; justify-content:center; font-size:.75rem; margin-right:8px;}
@media (prefers-color-scheme: dark) {.rs-step .rs-num {background:#fafafa; color:#18181b !important;}}
.rs-stats {display:flex; gap:10px; margin:6px 0 12px 0;}
.rs-stat {flex:1; border:1px solid #e4e4e7; border-radius:14px; padding:10px 14px; background:#fafafa;}
.rs-stat span {display:block; color:#71717a; font-size:.8rem;} .rs-stat b {font-size:1.35rem;}
video {max-height:560px; background:#000; border-radius:12px;}
@media (prefers-color-scheme: dark) {.rs-stat {background:#1f1f23; border-color:#3f3f46;}}
.rs-sec {font-weight:700; font-size:1.02rem; margin:2px 0 6px 0;}
.rs-muted {color:#71717a; font-size:.85rem;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius:16px;}
.stButton > button[kind="primary"] {border-radius:10px; font-weight:700; padding:.55rem 1.4rem;}
.stButton > button {border-radius:10px;}
@media (max-width: 640px) {
  .rs-steps {grid-template-columns:1fr;} .rs-hero {padding:16px;} .rs-hero h1 {font-size:1.35rem;}
  .block-container {padding: .6rem .6rem 4rem .6rem;}
}
@media (prefers-color-scheme: dark) {
  .rs-step {background:#1f1f23; border-color:#3f3f46;} .rs-step span {color:#a1a1aa;}
  .rs-gray {background:#27272a; color:#e4e4e7;}
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def pill(text, kind="gray"):
    return f'<span class="rs-pill rs-{kind}">{text}</span>'


# ---- sign-in: email and password accounts, first-time setup, forgot password (src/auth.py) ----
import auth
import mailer

_FAILS = st.cache_resource(lambda: {})()  # per email: failed tries and lock time


def _locked(email):
    return time.time() < _FAILS.get(email, {}).get("until", 0)


def _fail(email):
    f = _FAILS.setdefault(email, {"n": 0, "until": 0.0})
    f["n"] += 1
    if f["n"] >= 5:
        f["until"], f["n"] = time.time() + 60, 0


_TOP = None


def _auth_css(hello, line):
    with _TOP:
        _auth_head(hello, line)


def _auth_head(hello, line):
    st.markdown(
        '<style>.rs-login{max-width:480px;margin:6vh auto 0 auto;text-align:center;}'
        '.rs-login .logo{font-size:3rem;line-height:1;} .rs-login h2{margin:.6rem 0 .2rem 0;font-size:1.7rem;'
        'font-weight:800;letter-spacing:-0.02em;} .rs-login p{color:#71717a;margin:0 0 1.2rem 0;}'
        '.rs-login-foot{text-align:center;color:#a1a1aa;font-size:.82rem;margin-top:1rem;}</style>'
        f'<div class="rs-login"><div class="logo">🎬</div><h2>{hello}</h2><p>{line}</p></div>',
        unsafe_allow_html=True)


COOKIE = "rs_session"
KEEP_DAYS = auth.SESSION_DAYS


def _cookie_js(js):
    st.html(f"<script>(function(){{{js}}})();</script>", unsafe_allow_javascript=True)


def _enter(email, role, remember=False):
    st.session_state.update(signed_in=True, user_email=email, user_role=role, auth_view="signin")
    if remember:  # a random token goes into this browser's cookie; the server keeps only its hash
        tok = auth.create_session(email)
        st.session_state.update(session_token=tok, pending_cookie=tok)
    st.rerun()


def _auth_screen():
    hour = datetime.now().hour
    hello = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
    view = st.session_state.get("auth_view", "signin")
    if not auth.has_users():
        view = "setup"
    global _TOP
    _TOP = st.container()  # the greeting is drawn here, above the form
    _l, mid, _r = st.columns([1, 3, 1])

    if view == "setup":
        _auth_css("Welcome! 🎉", "Let's set up your reel studio. Create the owner account to begin.")
        with mid, st.form("setup", border=True):
            email = st.text_input("Your email", placeholder="you@example.com")
            pw = st.text_input("Choose a password", type="password", placeholder="At least 8 characters")
            pw2 = st.text_input("Type it again", type="password")
            if st.form_submit_button("Create my studio", type="primary", use_container_width=True):
                if pw != pw2:
                    st.error("The two passwords are not the same.")
                else:
                    err = auth.create_user(email, pw, "owner")
                    if err:
                        st.error(err)
                    else:
                        _enter(auth.norm(email), "owner")

    elif view == "signin":
        _auth_css(f"{hello}! 👋", "Welcome back. Sign in to open your reel studio.")
        with mid:
            if st.session_state.pop("pw_changed", False):
                st.success("Your password is changed. Please sign in.")
            with st.form("signin", border=True):  # a form, so pressing Enter works like the button
                email = st.text_input("Email", placeholder="you@example.com")
                pw = st.text_input("Password", type="password", placeholder="Your password")
                remember = st.checkbox(f"Keep me signed in for {KEEP_DAYS} days on this browser", value=True)
                go = st.form_submit_button("Sign in", type="primary", use_container_width=True)
            if go:
                e = auth.norm(email)
                if _locked(e):
                    st.warning("That was a few wrong tries in a row. Please wait a minute, then try again.")
                else:
                    role = auth.verify(e, pw)
                    if role:
                        _FAILS.pop(e, None)
                        _enter(e, role, remember)
                    else:
                        _fail(e)
                        time.sleep(1.2)
                        st.error("That email and password do not match. Please try again.")
            if st.button("Forgot your password?", type="tertiary"):
                st.session_state["auth_view"] = "forgot"
                st.rerun()

    elif view == "forgot":
        _auth_css("No problem 🙂", "Tell us your email and we will help you choose a new password.")
        with mid:
            with st.form("forgot", border=True):
                email = st.text_input("Your email", placeholder="you@example.com")
                go = st.form_submit_button("Send me a reset code", type="primary", use_container_width=True)
            if go:
                e = auth.norm(email)
                if auth.EMAIL_RE.match(e) and not _locked("reset:" + e):
                    _fail("reset:" + e)
                    auth.request_reset(e)
                    if mailer.available() and e in auth.list_users():
                        code = auth.issue_code(e)
                        try:
                            mailer.send(e, "Your Buzz reset code",
                                        f"Your code is {code}. It works for 15 minutes.\n\nIf you did not ask for "
                                        "this, you can ignore this email.")
                        except Exception:
                            pass
                st.session_state["reset_email"] = e
                st.session_state["auth_view"] = "reset"
                st.rerun()
            if st.button("← Back to sign in", type="tertiary"):
                st.session_state["auth_view"] = "signin"
                st.rerun()

    else:  # reset
        _auth_css("Check for your code ✉️", "Enter the 6-digit code, then pick a new password.")
        with mid:
            st.info("If that email has an account, a code is on its way. No email? Ask the studio owner for a code: "
                    "they can make one for you in Settings.")
            with st.form("reset", border=True):
                email = st.text_input("Your email", value=st.session_state.get("reset_email", ""))
                code = st.text_input("6-digit code", max_chars=6, placeholder="123456")
                pw = st.text_input("New password", type="password", placeholder="At least 8 characters")
                pw2 = st.text_input("Type the new password again", type="password")
                go = st.form_submit_button("Change my password", type="primary", use_container_width=True)
            if go:
                if pw != pw2:
                    st.error("The two passwords are not the same.")
                else:
                    err = auth.finish_reset(email, code, pw)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.update(auth_view="signin", pw_changed=True)
                        st.rerun()
            if st.button("← Back to sign in", type="tertiary", key="reset_back"):
                st.session_state["auth_view"] = "signin"
                st.rerun()


if not st.session_state.get("signed_in"):
    _tok = st.context.cookies.get(COOKIE)  # "keep me signed in": a valid cookie from this browser skips the sign-in
    _hit = auth.session_user(_tok) if _tok else None
    if _hit:
        st.session_state.update(signed_in=True, user_email=_hit[0], user_role=_hit[1], session_token=_tok)
    else:
        if st.session_state.pop("clear_cookie", False) or _tok:
            _cookie_js(f'document.cookie="{COOKIE}=; max-age=0; path=/; SameSite=Lax";')  # expired or signed out: forget it
        _auth_screen()
        footer()
        st.stop()
if st.session_state.get("pending_cookie"):
    _cookie_js(f'document.cookie="{COOKIE}={st.session_state.pop("pending_cookie")}; max-age={KEEP_DAYS * 86400}; '
               f'path=/; SameSite=Lax"+(location.protocol==="https:"?"; Secure":"");')
OWNER = st.session_state.get("user_role") == "owner"


def worker_state():
    hb = WORK / "heartbeat.txt"
    if not hb.exists():
        return False, "never started"
    age = time.time() - datetime.strptime(hb.read_text().strip(), "%Y-%m-%d %H:%M:%S").timestamp()
    return age < 90, f"seen {int(age)} s ago"


def start_worker():
    subprocess.run(["schtasks", "/Change", "/TN", TASK, "/ENABLE"], capture_output=True)
    subprocess.run(["schtasks", "/Run", "/TN", TASK], capture_output=True)


def stop_worker():
    subprocess.run(["schtasks", "/Change", "/TN", TASK, "/DISABLE"], capture_output=True)
    lock = WORK / "worker.lock"
    if lock.exists():
        subprocess.run(["taskkill", "/PID", lock.read_text().strip(), "/F"], capture_output=True)
        lock.unlink(missing_ok=True)


# ---- header ----
ok, detail = worker_state()
st.markdown(
    '<div class="rs-hero"><div><h1>🎬 Buzz</h1>'
    '<p><b>AI Reel Studio.</b> Photos, clips or just an idea in. An Instagram-ready reel out, with caption and hashtags.</p></div>'
    f'<div>{pill("● Worker running", "green") if ok else pill("● Worker stopped", "red")}</div></div>',
    unsafe_allow_html=True)
if not ok:
    c1, c2 = st.columns([3, 1])
    c1.warning("The background worker is stopped, so new reels will not start.")
    if c2.button("Start worker", type="primary", use_container_width=True):
        start_worker()
        st.toast("Start requested. Refresh in a few seconds.")

who1, who2 = st.columns([5, 1])
who1.caption(f"Signed in as {st.session_state.get('user_email')}")
if who2.button("Sign out", key="signout", use_container_width=True):
    auth.end_session(st.session_state.get("session_token"))
    for _k in ("signed_in", "user_email", "user_role", "session_token"):
        st.session_state.pop(_k, None)
    st.session_state["clear_cookie"] = True
    st.rerun()


if not keyring.get_password(SERVICE, "anthropic"):
    st.warning("**One step left:** open the **Settings** tab and paste your Claude key in the Claude card. Reels cannot be made until then.")


def nav_tabs(options, value, key):
    """shadcn tabs; if that component cannot load for any reason, plain buttons keep the page usable."""
    try:
        return ui.tabs(options, value=value, key=key)
    except Exception:
        return st.radio("Go to", options, index=options.index(value), horizontal=True, key=key + "_fb",
                        label_visibility="collapsed")


page = nav_tabs(["Create", "My reels", "Settings"], "Create", "page_tab")


# ---------------------------------------------------------------- helpers
def font_sample(key, label, path):
    """Small picture of the font so the choice can be seen before uploading."""
    from PIL import Image, ImageDraw, ImageFont
    out = WORK / "fontprev" / f"{key}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGB", (520, 86), (24, 24, 28))
        font = ImageFont.truetype(str(path or Path("C:/Windows/Fonts/palab.ttf")), 46)
        ImageDraw.Draw(im).text((16, 12), "Diwali Ride 2026", font=font, fill=(255, 153, 51), stroke_width=2,
                                stroke_fill=(122, 12, 20))
        im.save(out)
    return out


def new_folder(rname):
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", rname).strip()[:60] or "New reel"
    dest, k = REELS_IN / safe, 2
    while dest.exists():
        dest, k = REELS_IN / f"{safe} {k}", k + 1
    dest.mkdir(parents=True)
    return dest


def font_picker(prefix):
    from render import FONTS
    keys = list(FONTS)
    choice = st.selectbox("Text font", keys, format_func=lambda k: FONTS[k][0], key=prefix + "font")
    if choice != "auto":
        st.image(str(font_sample(choice, *FONTS[choice])), width=360)
    with st.expander("See all fonts"):
        cols = st.columns(2)
        for n, k in enumerate(keys[1:]):
            cols[n % 2].image(str(font_sample(k, *FONTS[k])), caption=FONTS[k][0])
    return choice


def section(title, hint=None):
    st.markdown(f'<div class="rs-sec">{title}</div>' + (f'<div class="rs-muted">{hint}</div>' if hint else ""),
                unsafe_allow_html=True)


def voice_sample_button(voice, key):
    import voice_provider
    if st.button("▶ Hear this voice", key=key):
        try:
            mp3 = WORK / "voice_sample.mp3"
            voice_provider.synth("Hi! This is how your reel will sound. Three simple habits, and your ride is better.",
                                 mp3, voice)
            st.audio(str(mp3))
        except Exception as e:
            st.error(str(e)[:200])


# ---------------------------------------------------------------- create
def sound_block(prefix, music_label, default_music=True):
    """Music and voiceover choices, the same in both forms. Returns (music_on, voice_on, voice_name)."""
    import voice_provider as vp
    have_voice = vp.available()
    mkmusic = st.checkbox(music_label, value=default_music, key=prefix + "mus")
    keywords = ""
    if mkmusic:
        keywords = st.text_input("What type of music would you like? Up to 3 keywords", key=prefix + "mkw",
                                 max_chars=60, placeholder="e.g. calm, acoustic, sunrise")
        st.caption("Try: festive, devotional, calm, chill, energetic, epic, romantic, dance, happy. "
                   "Leave it empty and the music is matched to your reel.")
    voice_on = st.checkbox("Add a voiceover", value=have_voice, disabled=not have_voice, key=prefix + "voice")
    voice_name = vp.default_voice()
    if have_voice:
        _vs = vp.voices()
        voice_name = st.selectbox("Voice", list(_vs), format_func=lambda k: _vs[k], key=prefix + "vname",
                                  disabled=not voice_on)
        if voice_on:
            voice_sample_button(voice_name, prefix + "hear")
    else:
        st.caption("Voiceover is off until a voice is set up under Settings (a free voice or a Google key).")
    import music_provider
    return mkmusic, voice_on, voice_name, music_provider.clean_keywords(keywords)


def length_picker(prefix, auto=True):
    """Reel length in seconds. Returns None for 'Auto (best fit)'."""
    opts = (["Auto"] if auto else []) + [15, 20, 30, 45, 60, 90]
    v = st.segmented_control("Reel length", options=opts, default="Auto" if auto else 30, key=prefix + "len",
                             format_func=lambda x: "Auto" if x == "Auto" else f"{x}s")
    st.caption("Auto lets the reel fit your pictures and music." if auto else "How long the reel should run.")
    if v in (None, "Auto"):
        return None if auto else 30
    return int(v)


def assets_picker(n_media, secs):
    """How many of the uploaded pictures and clips to use. Returns None (Auto), "all" or a number."""
    mode = st.segmented_control("Pictures and clips to use", ["Auto", "All", "A number"], default="Auto",
                                key="up_amode") or "Auto"
    value, count = None, n_media
    if mode == "All":
        value = "all"
    elif mode == "A number":
        count = int(st.number_input("How many?", min_value=1, max_value=500, value=10, step=1, key="up_acount"))
        value = count
    st.caption({"Auto": "Auto: the best pictures and clips are chosen for the reel length. Good for big collections.",
                "All": "All: every picture and clip you add is used, in the best order.",
                "A number": "A number: that many of the best pictures and clips are used."}[mode])
    if n_media:
        st.caption(f"You have added {n_media} pictures and clips.")
    if mode == "A number" and n_media and count > n_media:
        st.warning(f"You asked for {count} but added only {n_media}, so all {n_media} will be used.")
        count = n_media
    if mode != "Auto" and count:
        if secs is None:
            st.info(f"The reel will be about {min(90, max(15, round(count * 3.0)))} seconds long, so each one stays on "
                    "screen long enough to enjoy.")
        else:
            each = secs / count
            if count > int(secs // 1.2):
                st.warning(f"{count} pictures and clips do not fit in {secs} seconds. About {int(secs // 1.2)} will be used. "
                           "Choose a longer reel to use more.")
            elif each < 1.6:
                st.warning(f"That is about {each:.1f} seconds for each one, which is very quick. A longer reel or fewer "
                           "pictures looks better.")
            elif each > 8:
                st.info(f"Each one will stay on screen for about {each:.0f} seconds. Choose a shorter reel or more "
                        "pictures if that feels slow.")
    return value


def shot_pickers(files):
    """Lets the owner choose the opening and closing picture or clip from what was uploaded.
    Returns (opening_upload_name or None, closing_upload_name or None); None means 'Auto'."""
    import uploads
    media = [f for f in files or [] if Path(f.name).suffix.lower() in (uploads.PHOTO | uploads.VIDEO)]
    if not media:
        st.caption("Opening and closing shot: add pictures or clips first, then you can choose them here.")
        return None, None
    names = [f.name for f in media]
    by_name = {f.name: f for f in media}
    st.markdown("**Opening and closing shot** (optional)")
    c1, c2 = st.columns(2)
    out = []
    for col, label, key in ((c1, "Opening shot", "up_open"), (c2, "Closing shot", "up_close")):
        with col:
            pick = st.selectbox(label, ["Auto (chosen for me)"] + names, key=key)
            if pick in by_name:
                f = by_name[pick]
                if Path(f.name).suffix.lower() in uploads.PHOTO:
                    try:
                        import pillow_heif
                        from PIL import Image, ImageOps
                        pillow_heif.register_heif_opener()
                        with Image.open(f) as im:
                            im = ImageOps.exif_transpose(im).convert("RGB")
                            im.thumbnail((260, 260))
                            st.image(im)
                    except Exception:
                        st.caption("(no preview for this picture)")
                else:
                    st.caption(f"Video, {len(f.getbuffer()) / 1e6:.1f} MB")
            out.append(pick if pick in by_name else None)
    if out[0] and out[0] == out[1]:
        st.warning("The opening and closing shot are the same file. Only the opening will be fixed.")
        out[1] = None
    st.caption("Auto lets the story decide: a strong hook first and a warm group picture last when there is one.")
    return out[0], out[1]


def refused_note(refused):
    if refused:
        st.warning("Some files were not accepted: " + "; ".join(f"{n} ({why})" for n, why in refused[:6])
                   + ("; and more" if len(refused) > 6 else ""))


def upload_form():
    import uploads
    with st.container(border=True):
        section("1. Your material")
        rname = st.text_input("Reel name", key="rname", placeholder="Diwali ride 2026")
        files = st.file_uploader("Photos and videos (a song here works too)", accept_multiple_files=True, key="ups",
                                 type=uploads.types(uploads.PHOTO, uploads.VIDEO, uploads.AUDIO))
        st.caption("Accepted: JPG, PNG, HEIC, WEBP, MP4, MOV, MKV, WEBM, MP3, WAV, M4A and similar picture, video and "
                   "sound files. Anything else is refused.")
        brief = st.text_area("Brief (optional): subject, mood, title. Add your own logo below to brand the reel.",
                             key="rbrief", height=90)
        secs = length_picker("up_")
        n_media = sum(1 for f in files or [] if Path(f.name).suffix.lower() in (uploads.PHOTO | uploads.VIDEO))
        assets = assets_picker(n_media, secs)
        open_pick, close_pick = shot_pickers(files)
        attach = st.multiselect("Attach (optional)", ["Upload logo", "Upload music"], key="attach")
        logo_up = music_up = None
        if "Upload logo" in attach:
            logo_up = st.file_uploader("Logo (PNG with transparent background works best)",
                                       type=uploads.types(uploads.LOGO), key="logoup")
        if "Upload music" in attach:
            music_up = st.file_uploader("Music (your own song, one file)", type=uploads.types(uploads.AUDIO),
                                        key="musicup")
    with st.container(border=True):
        section("2. Sound")
        mkmusic, voice_on, voice_name, mkw = sound_block("up_", "Create and add music for me (used when you do not upload a song)")
    with st.container(border=True):
        section("3. Look")
        fchoice = font_picker("up_")
        crop = st.checkbox("Crop and centre portrait pictures to fill the 9:16 screen", key="optcrop")
        collage = st.checkbox("Make collages of landscape pictures (2 or 3 in one frame, no blurred bars)", key="optcol")
    sig = (rname.strip(), tuple((f.name, f.size) for f in files or []), brief.strip(), fchoice, crop, collage, mkmusic,
           voice_on, voice_name, secs, mkw, assets, open_pick, close_pick, logo_up.name if logo_up else "", music_up.name if music_up else "")
    go = st.button("Upload and make my reel", type="primary", key="go_up", use_container_width=True)
    if go and not (rname.strip() and (files or music_up)):
        st.warning("Give the reel a name and add at least one photo or video.")
    elif go and st.session_state.get("last_up") == sig:
        st.info("Already uploaded. Change the name or files to upload another reel.")
    elif go:
        st.session_state["last_up"] = sig  # stops a double click making two copies
        dest = new_folder(rname)
        media = [f for f in files or [] if not (music_up and Path(f.name).suffix.lower() in uploads.AUDIO)]  # the music box wins
        names_map = {}
        saved, refused = uploads.save(dest, media, uploads.PHOTO | uploads.VIDEO | uploads.AUDIO, mapping=names_map)
        if music_up:
            s2, r2 = uploads.save(dest, [music_up], uploads.AUDIO)
            saved, refused = saved + s2, refused + r2
        if logo_up:
            lext = Path(logo_up.name).suffix.lower()
            if lext in uploads.LOGO and uploads.looks_right(lext, bytes(logo_up.getbuffer()[:16])):
                (dest / ("_logo" + lext)).write_bytes(logo_up.getbuffer())
            else:
                refused.append((logo_up.name, "not a valid logo picture"))
        refused_note(refused)
        if not saved:
            for p in dest.iterdir():
                if p.is_file() and p.name.startswith("_logo"):
                    p.unlink()
            dest.rmdir()
            st.error("None of the files could be used, so nothing was started. Please add photos or videos.")
        else:
            if brief.strip():
                (dest / "brief.txt").write_bytes(brief.strip().encode("utf-8"))
            (dest / "options.json").write_text(json.dumps({
                "font": fchoice, "crop_portrait": crop, "collage": collage, "music": "create" if mkmusic else "none",
                "voice": bool(voice_on), "voice_name": voice_name, "seconds": secs, "music_keywords": mkw,
                "assets": assets, "opening": names_map.get(open_pick), "closing": names_map.get(close_pick)}), encoding="utf-8")
            st.success(f"Uploaded '{dest.name}'. It starts in about 2 minutes. Watch it under My reels.")
            st.toast("Reel queued")


def theme_sample(key):
    """Small swatch picture of a colour theme: its background, text colour and accent."""
    from PIL import Image, ImageDraw, ImageFont
    import prompt_reel as pr
    out = WORK / "themeprev" / f"{key}_v2.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        top, bot, fg, edge, acc = pr.LOOKS[key]
        w, h = 200, 120
        im = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(im)
        for y in range(h):
            d.line([(0, y), (w, y)], fill=tuple(int(top[k] + (bot[k] - top[k]) * y / h) for k in range(3)))
        font = ImageFont.truetype("C:/Windows/Fonts/georgiab.ttf", 40)
        d.text((16, 22), "Aa Reel", font=font, fill=fg, stroke_width=2, stroke_fill=edge)
        d.rounded_rectangle([16, 84, 96, 92], radius=4, fill=acc)
        im.save(out)
    return out


def theme_picker():
    """Colour theme for idea reels. Returns a theme key, or None for 'match my topic'."""
    import prompt_reel as pr
    keys = ["auto"] + list(pr.LOOKS)
    choice = st.selectbox("Colour theme", keys, key="id_theme",
                          format_func=lambda k: "Auto: matched to my topic" if k == "auto" else pr.LOOK_NAMES[k])
    if choice != "auto":
        st.image(str(theme_sample(choice)), width=200)
    with st.expander("See all colour themes"):
        cols = st.columns(5)
        for n, k in enumerate(pr.LOOKS):
            cols[n % 5].image(str(theme_sample(k)), caption=pr.LOOK_NAMES[k])
    return None if choice == "auto" else choice


def background_picker(have_stock):
    """What goes behind the words. Returns gradient | solid | art | video."""
    import art_provider
    have_art = art_provider.available()
    opts = {"gradient": "Soft colour gradient (text only)", "solid": "Plain solid colour (text only)"}
    if have_art:
        opts["art"] = "Pictures made for my topic (one drawn for each scene)"
    if have_stock:
        opts["video"] = "Real video clips (Pexels)"
    hints = {"gradient": "Smooth colours with soft glows. Clean and fast.",
             "solid": "One flat colour, nothing else.",
             "art": "Friendly illustrations drawn for your words. Takes about a minute longer.",
             "video": "Real moving footage behind some scenes."}
    key = st.radio("Background", list(opts), format_func=opts.get, key="id_bg", captions=[hints[k] for k in opts])
    if not have_stock:
        st.caption("Real video clips appear here once a Pexels key is added under Settings.")
    return key


def idea_form():
    import stock_provider
    have_stock = stock_provider.available()
    with st.container(border=True):
        section("1. Your idea", "No photos needed. It writes the script, builds the scenes and prepares the post text.")
        rname = st.text_input("Reel name", key="iname", placeholder="3 habits for safer rides")
        idea = st.text_area("Describe the reel: topic, who it is for, tone, any title or call to action",
                            height=140, key="idea")
        secs = length_picker("id_", auto=False)
        lang = st.selectbox("Language", ["English"], key="ilang")
    with st.container(border=True):
        section("2. Sound")
        mkmusic, voice_on, voice_name, mkw = sound_block("id_", "Create and add music for me")
    with st.container(border=True):
        section("3. Look")
        bg = background_picker(have_stock)
        theme = theme_picker()
        fchoice = font_picker("id_")
    sig = (rname.strip(), idea.strip(), secs, fchoice, mkmusic, mkw, voice_on, voice_name, bg, theme)
    go = st.button("Create my reel", type="primary", key="go_idea", use_container_width=True)
    if go and not (rname.strip() and idea.strip()):
        st.warning("Give the reel a name and describe the idea.")
    elif go and st.session_state.get("last_idea") == sig:
        st.info("Already sent. Change the name or idea to make another reel.")
    elif go:
        st.session_state["last_idea"] = sig
        dest = new_folder(rname)
        (dest / "prompt.txt").write_bytes(idea.strip().encode("utf-8"))
        (dest / "options.json").write_text(json.dumps({
            "mode": "prompt", "seconds": secs, "language": lang, "font": fchoice,
            "music": "create" if mkmusic else "none", "voice": bool(voice_on), "voice_name": voice_name,
            "background": bg, "stock": bg == "video", "look": theme, "music_keywords": mkw}), encoding="utf-8")
        st.success(f"Sent '{dest.name}'. It starts in about 2 minutes. Watch it under My reels.")
        st.toast("Reel queued")


def create_tab():
    st.markdown(
        '<div class="rs-steps">'
        '<div class="rs-step"><b><span class="rs-num">1</span>Choose</b><span>Upload photos and clips, or just '
        'describe an idea.</span></div>'
        '<div class="rs-step"><b><span class="rs-num">2</span>Style it</b><span>Pick a font, music, voice and '
        'layout options.</span></div>'
        '<div class="rs-step"><b><span class="rs-num">3</span>Post it</b><span>Get the reel plus caption and '
        'hashtags ready to paste.</span></div></div>', unsafe_allow_html=True)
    mode = nav_tabs(["From photos and videos", "From an idea"], "From photos and videos", "mode_tab")
    if mode == "From an idea":
        idea_form()
    else:
        upload_form()
    st.markdown(f'<div class="rs-muted">You can also drop a folder into <code>{REELS_IN}</code>. '
                f'It starts by itself about 2 minutes after the copy finishes.</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- my reels
STAGES = {"catalogue": (12, "Reading your files"), "ai_analysis": (35, "Looking at the pictures"),
          "planning": (55, "Planning the story"), "rendering": (80, "Making the video"),
          "finished": (100, "Finished")}
QUICK = {"Shorter": "make it shorter", "More energetic": "make it more energetic", "Calmer": "make it calmer",
         "Remove music": "remove the music"}


def nice_name(jd, ext=".mp4"):
    """A readable file name for downloads: the reel's name plus its title, e.g. 'Diwali ride - Sunrise Sparklers.mp4'."""
    title = ""
    try:
        p = json.loads((jd / "plan.json").read_text(encoding="utf-8"))
        title = (p.get("title") or "").replace("\n", " ").replace("|", " ").strip()
        if not title:
            title = " ".join((p.get("concept") or "").split()[:6])
    except Exception:
        pass
    base = jd.name if (not title or title.lower() in jd.name.lower()) else f"{jd.name} - {title}"
    base = re.sub(r"\s+", " ", re.sub(r"[^\w .()\-]", "", base)).strip()[:100] or "reel"
    return base + ext


def insta_pack(out, jname):
    pj = out / "instagram.json"
    if not pj.exists():
        st.info("The Instagram pack appears here when the reel is finished.")
        return
    pack = json.loads(pj.read_text(encoding="utf-8"))
    post = f"{pack.get('hook', '')}\n\n{pack.get('caption', '')}"
    tag_list = pack.get("hashtags", [])[:5]  # Instagram allows five hashtags at most
    tags = " ".join(tag_list)
    st.text_area("Post text (the first line is the hook)", post, height=170, key="cap" + jname)
    st.caption("Hashtags: the best 5 (Instagram allows no more). Tap the copy icon.")
    st.code(tags, language=None, wrap_lines=True)
    st.markdown(f'<span class="rs-muted">Cover text: <b>{pack.get("cover_text", "")}</b></span><br>'
                f'<span class="rs-muted">{pack.get("best_time", "")}</span>', unsafe_allow_html=True)
    for c in pack.get("credits", []):
        st.caption(f"Credit to add in your post: {c}")
    body = (f"{post}\n\n{tags}\n\nCover text: {pack.get('cover_text', '')}\nBest time to post: {pack.get('best_time', '')}\n"
            f"Alt text: {pack.get('alt_text', '')}\n" + "".join(f"Credit: {c}\n" for c in pack.get("credits", [])))
    st.download_button("Download the pack (.txt)", body.encode("utf-8"),
                       file_name=nice_name(WORK / "jobs" / jname, " - Instagram post.txt"), key="dl" + jname)


@st.fragment(run_every=1.0)
def live_progress(jname):
    """A progress bar that updates every second from the worker's real reports and creeps forward between them,
    never past the point the next report is allowed to reach, and never backwards."""
    jd = WORK / "jobs" / jname
    try:
        p = json.loads((jd / "progress.json").read_text(encoding="utf-8"))
    except Exception:
        p = {}
    now = time.time()
    pct = float(p.get("pct", 1))
    ceil = float(p.get("ceil", pct + 3))
    shown = min(pct + max(now - p.get("t", now), 0) * 0.6, max(pct, ceil - 0.4))
    key = "_shown_" + jname
    prev = st.session_state.get(key, 0.0)
    shown = max(shown, prev) if prev - shown < 8 else shown  # a restart of the job may legitimately go back
    st.session_state[key] = shown
    took = int(now - p["t0"]) if p.get("t0") else 0
    st.progress(min(shown, 99.5) / 100, text=f"{p.get('text', 'Working')}  ·  {int(shown)}%  ·  {took // 60}:{took % 60:02d} elapsed")


def reel_card(jd, first):
    job = json.loads((jd / "job.json").read_text(encoding="utf-8"))
    rev = jd / "revision_result.json"
    revs = json.loads(rev.read_text(encoding="utf-8")) if rev.exists() else {}
    status = job.get("status")
    out = REELS_OUT / jd.name
    reel = out / f"{jd.name} reel.mp4"
    changing = revs.get("state") == "working" or (jd / "revision_request.txt").exists()
    kind = {"done": "green", "running": "amber", "failed": "red"}.get(status, "gray")
    label = {"done": "Ready", "running": "Working", "failed": "Needs attention"}.get(status, status or "")
    if changing:
        kind, label = "amber", "Applying a change"
    with st.container(border=True):
        h1, h2 = st.columns([3, 1])
        h1.markdown(f"**{jd.name}**")
        h2.markdown(f'<div style="text-align:right">{pill(label, kind)}</div>', unsafe_allow_html=True)
        if status == "running" or revs.get("state") == "working":
            live_progress(jd.name)
        elif changing:
            st.progress(0.03, text="Your change is queued. The worker picks it up within seconds.")
        if status == "failed":
            st.error(job.get("error", "Something went wrong. See Work\\jobs\\%s\\error.log" % jd.name))
            if st.button("Try again", key="retry" + jd.name, type="primary"):
                (jd / "job.json").unlink()
                st.rerun()
        if not reel.exists():
            return
        left, right = st.columns([2, 3])
        with left:
            st.video(str(reel))
            st.caption(f"{job.get('seconds', 0):.0f} seconds")
            kept = (jd / "keep.flag").exists()
            if st.toggle(f"Keep this reel beyond {HISTORY_DAYS} days", value=kept, key="keep" + jd.name,
                         help="Kept reels are never hidden or cleaned up automatically") != kept:
                import cleanup
                cleanup.set_kept(jd.name, not kept)
                st.rerun()
            st.download_button("⬇ Download video", data=lambda r=reel: r.read_bytes(), file_name=nice_name(jd),
                               mime="video/mp4", key="dlv" + jd.name, use_container_width=True,
                               help="Saves the reel with a clear file name")
        with right:
            t1, t2, t3 = st.tabs(["Instagram pack", "Make a change", "Details"])
            with t1:
                insta_pack(out, jd.name)
            with t2:
                if revs.get("reply") and not changing:
                    st.success(f"Last change: {revs['reply']}")
                cols = st.columns(len(QUICK))
                for c, (lab, note) in zip(cols, QUICK.items()):
                    if c.button(lab, key=f"q{lab}{jd.name}", use_container_width=True):
                        (jd / "revision_request.txt").write_text(note, encoding="utf-8")
                        st.rerun()
                note = st.text_area("Or say it in your own words, one change at a time",
                                    key="note" + jd.name, height=90,
                                    placeholder="change the title to Beat the Smog, use the Cinzel font, drop shot 3")
                if st.button("Send change", key="send" + jd.name, type="primary") and note.strip():
                    (jd / "revision_request.txt").write_text(note.strip(), encoding="utf-8")
                    st.rerun()
                st.caption("The new version replaces the file above. The old one is kept as '(previous)'.")
            with t3:
                summ = out / "summary.txt"
                if summ.exists():
                    st.text(summ.read_text(encoding="utf-8"))
                st.code(str(reel), language=None)
                if (out / "instagram_error.log").exists():
                    st.warning("The Instagram pack could not be written this time.")


def queued_folders():
    """Folders in Reels In that the worker has not started yet (it waits about 2 minutes after the last file arrives)."""
    done = {p.name for p in (WORK / "jobs").glob("*") if (p / "job.json").exists()}
    return sorted((p for p in REELS_IN.glob("*") if p.is_dir() and p.name not in done and not p.name.startswith("_")
                   and any(f.is_file() for f in p.rglob("*"))),  # an empty folder is not a reel
                  key=lambda p: p.stat().st_mtime, reverse=True)


def queued_card(folder):
    with st.container(border=True):
        h1, h2 = st.columns([3, 1])
        h1.markdown(f"**{folder.name}**")
        h2.markdown(f'<div style="text-align:right">{pill("Waiting to start", "amber")}</div>', unsafe_allow_html=True)
        st.progress(0.05, text="Received. The worker starts it about 2 minutes after the last file arrived.")


def last_touched(jd):
    """When a reel last changed: its job file, a change note result, or its finished video."""
    times = [(jd / n).stat().st_mtime for n in ("job.json", "revision_result.json") if (jd / n).exists()]
    reel = REELS_OUT / jd.name / f"{jd.name} reel.mp4"
    if reel.exists():
        times.append(reel.stat().st_mtime)
    return max(times) if times else 0


def reels_tab():
    all_jobs = sorted((p for p in (WORK / "jobs").glob("*") if (p / "job.json").exists() and not p.name.startswith("_")),
                      key=last_touched, reverse=True)
    cutoff = time.time() - HISTORY_DAYS * 86400
    jobs = [p for p in all_jobs if last_touched(p) >= cutoff or (p / "keep.flag").exists()
            or (json.loads((p / "job.json").read_text(encoding="utf-8")).get("status") == "running")]
    hidden = len(all_jobs) - len(jobs)
    queued = queued_folders()
    if not jobs and not queued:
        with st.container(border=True):
            st.markdown("**No reels yet.** Make your first one on the Create tab." if not hidden else
                        f"**No reels in the last {HISTORY_DAYS} days.** Make a new one on the Create tab.")
        return
    stats = [json.loads((p / "job.json").read_text(encoding="utf-8")).get("status") for p in jobs]
    busy = stats.count("running") + len(queued) + sum(1 for p in jobs if (p / "revision_request.txt").exists())
    st.markdown(
        '<div class="rs-stats">'
        f'<div class="rs-stat"><span>Reels</span><b>{len(jobs) + len(queued)}</b></div>'
        f'<div class="rs-stat"><span>Ready</span><b>{stats.count("done")}</b></div>'
        f'<div class="rs-stat"><span>In progress</span><b>{busy}</b></div></div>',
        unsafe_allow_html=True)
    for q in queued:
        queued_card(q)
    for n, jd in enumerate(jobs):
        reel_card(jd, n == 0 and not queued)
    st.caption(f"Reels are kept for {HISTORY_DAYS} days here." + (f" {hidden} older reel{'s are' if hidden != 1 else ' is'} hidden." if hidden else ""))


def _signature():
    """Changes whenever a reel starts, moves to a new stage, finishes or gets a change note, or the worker stops/starts."""
    parts = [worker_state()[0]]
    for p in sorted((WORK / "jobs").glob("*")):
        jf = p / "job.json"
        if jf.exists():
            rr = p / "revision_result.json"
            parts.append((p.name, jf.stat().st_mtime_ns, (p / "revision_request.txt").exists(),
                          rr.stat().st_mtime_ns if rr.exists() else 0))
    parts.append([q.name for q in queued_folders()])
    return str(parts)


@st.fragment(run_every=4)
def watch_for_changes():
    """Checks every 4 seconds and refreshes the whole page only when something actually changed."""
    sig = _signature()
    old = st.session_state.get("_sig")
    st.session_state["_sig"] = sig
    if old is not None and old != sig:
        st.rerun()


# ---------------------------------------------------------------- settings
def key_card(title, blurb, entry, save_fn, key_prefix, sample=None):
    saved = bool(keyring.get_password(SERVICE, entry))
    with st.container(border=True):
        a, b = st.columns([3, 1])
        a.markdown(f"**{title}**")
        b.markdown(f'<div style="text-align:right">{pill("Connected", "green") if saved else pill("Not set", "gray")}</div>',
                   unsafe_allow_html=True)
        st.caption(blurb)
        val = st.text_input("Key (stored in Windows Credential Manager, never shown again)", type="password",
                            key=key_prefix + "_in", placeholder="Paste the key here")
        c1, c2 = st.columns(2)
        if c1.button("Save key", key=key_prefix + "_save", type="primary", use_container_width=True):
            if val.strip():
                save_fn(val)
                st.success("Saved.")
                st.rerun()
            else:
                st.warning("Paste the key first.")
        if saved and c2.button("Remove key", key=key_prefix + "_del", use_container_width=True):
            keyring.delete_password(SERVICE, entry)
            st.rerun()
        if saved and sample:
            sample()


def account_section():
    section("Your account")
    with st.container(border=True):
        st.markdown(f"**{st.session_state.get('user_email')}**  " + pill("Owner" if OWNER else "Member", "gray"),
                    unsafe_allow_html=True)
        with st.form("chpw", border=False):
            old = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password", placeholder="At least 8 characters")
            new2 = st.text_input("New password again", type="password")
            if st.form_submit_button("Change my password"):
                if new != new2:
                    st.error("The two new passwords are not the same.")
                elif not auth.verify(st.session_state.get("user_email"), old):
                    st.error("The current password is not right.")
                else:
                    err = auth.set_password(st.session_state.get("user_email"), new)
                    st.error(err) if err else st.success("Password changed.")


def people_section():
    section("People", "Who can sign in. Add a teammate with a first password, and ask them to change it.")
    with st.container(border=True):
        for email, role in auth.list_users().items():
            a, b = st.columns([4, 1])
            a.markdown(f"{email}  " + pill("Owner" if role == "owner" else "Member", "gray"), unsafe_allow_html=True)
            if role != "owner" and b.button("Remove", key="rm" + email):
                auth.remove_user(email)
                st.rerun()
        with st.form("adduser", border=False):
            e1, e2 = st.columns(2)
            ne = e1.text_input("Their email", placeholder="name@example.com")
            npw = e2.text_input("First password", type="password", placeholder="At least 8 characters")
            if st.form_submit_button("Add person"):
                err = auth.create_user(ne, npw, "member")
                st.error(err) if err else st.success(f"Added {auth.norm(ne)}.")
                if not err:
                    st.rerun()
    pend = auth.pending_requests()
    if pend:
        section("Password reset requests", "These people pressed 'Forgot your password'. Make a one-time code and "
                "tell it to them. It works for 15 minutes.")
        with st.container(border=True):
            for email in pend:
                a, b = st.columns([3, 2])
                a.markdown(email)
                if b.button("Make a reset code", key="code" + email, use_container_width=True):
                    st.session_state["shown_code"] = (email, auth.issue_code(email))
            sc = st.session_state.get("shown_code")
            if sc and sc[1]:
                st.success(f"Code for {sc[0]}: **{sc[1]}**  (shown once, valid 15 minutes)")


def mail_section():
    section("Email sending", "Optional. Lets the page email reset codes by itself. Use a mailbox you own, for "
            "example a Gmail address with an app password.")
    on = mailer.available()
    with st.container(border=True):
        a, b = st.columns([3, 1])
        a.markdown("**Reset codes by email**")
        b.markdown(f'<div style="text-align:right">{pill("Connected", "green") if on else pill("Not set", "gray")}</div>',
                   unsafe_allow_html=True)
        c1, c2 = st.columns([3, 1])
        host = c1.text_input("Mail server", value="smtp.gmail.com", key="mh")
        port = c2.text_input("Port", value="587", key="mp")
        user = st.text_input("Mailbox address", key="mu", placeholder="studio@example.com")
        pwd = st.text_input("App password (kept in Windows Credential Manager)", type="password", key="mw")
        d1, d2, d3 = st.columns(3)
        if d1.button("Save", key="mail_save", type="primary", use_container_width=True):
            if host and port.isdigit() and user and pwd:
                mailer.save(host, port, user, pwd)
                st.rerun()
            else:
                st.warning("Fill in all four boxes.")
        if on and d2.button("Send a test", key="mail_test", use_container_width=True):
            try:
                mailer.send(st.session_state.get("user_email"), "Reel studio test", "Email sending works.")
                st.success("Test sent to your own email.")
            except Exception as e:
                st.error(f"Could not send: {str(e)[:150]}")
        if on and d3.button("Remove", key="mail_del", use_container_width=True):
            mailer.clear()
            st.rerun()


def cleanup_section():
    import cleanup
    section("Automatic cleanup", f"Every night around {cleanup.RUN_HOUR} AM, reels older than {HISTORY_DAYS} days are moved to a holding "
            f"folder and deleted for good after {cleanup.TRASH_DAYS} more days. Reels marked Keep, reels being made, and folders "
            "you dropped into Reels In yourself are never touched.")
    with st.container(border=True):
        state = cleanup._read_state().get("last")
        if state:
            st.caption(f"Last run: {state['when']}. Moved {len(state['moved'])} reel(s), {cleanup.mb(state['bytes'])}. "
                       f"Permanently deleted {cleanup.mb(state['purged_bytes'])}.")
        else:
            st.caption("Has not run yet.")
        a, b = st.columns(2)
        if a.button("Preview what would be removed", use_container_width=True, key="cl_prev"):
            r = cleanup.run(dry=True)
            st.info("Nothing is due right now." if not r["moved"] else
                    f"Would move {len(r['moved'])} reel(s) ({cleanup.mb(r['bytes'])}): " + ", ".join(r["moved"]))
        if b.button("Run cleanup now", use_container_width=True, key="cl_run"):
            if cleanup.any_running():
                st.warning("A reel is being made right now. Try again when it is finished.")
            else:
                r = cleanup.run()
                st.success(f"Moved {len(r['moved'])} reel(s) to the holding folder ({cleanup.mb(r['bytes'])}).")
        held = cleanup.trashed()
        if held:
            st.markdown("**In the holding folder** (put back with one click)")
            for h in held:
                x, y = st.columns([3, 1])
                x.caption(f"{h['name']} · {cleanup.mb(h['bytes'])} · removed {h['stamp'][:8]}")
                if y.button("Put back", key=f"cl_back{h['stamp']}{h['name']}"):
                    cleanup.restore(h["stamp"], h["name"])
                    st.rerun()


def kokoro_card():
    import voice_provider as vp
    ready = vp.kokoro_ready()
    with st.container(border=True):
        a, b = st.columns([3, 1])
        a.markdown("**Free voice (Kokoro)**")
        b.markdown(f'<div style="text-align:right">{pill("Installed", "green") if ready else pill("Not installed", "gray")}</div>',
                   unsafe_allow_html=True)
        st.caption("A free, open-source English voice that runs on this PC. No key and no account. "
                   "One-time download of about 330 MB. Details: github.com/thewh1teagle/kokoro-onnx")
        if not ready and st.button("Install the free voice", key="ko_install", type="primary"):
            with st.spinner("Downloading the voice. This takes a few minutes..."):
                try:
                    vp.install_kokoro()
                except Exception as e:
                    st.error(f"Download failed: {str(e)[:150]}")
            st.rerun()
        if ready:
            voice_sample_button(vp.KOKORO_DEFAULT, "ko_hear")


def settings_tab():
    import stock_provider
    import voice_provider
    account_section()
    if not OWNER:
        return
    people_section()
    mail_section()
    section("Connections", "Optional add-ons. The app works fully without them.")
    kokoro_card()
    key_card("Google voice (Text-to-Speech)", "Natural English voices with Indian accents too. Needs your own key from "
             "console.cloud.google.com (free monthly allowance).", voice_provider.ENTRY, voice_provider.save_key, "gv",
             sample=lambda: voice_sample_button(voice_provider.DEFAULT_VOICE, "gv_hear"))
    key_card("Pexels (stock video)", "Free real video clips behind idea-reel scenes. Reels with Pexels footage "
             "carry a credit line in the Instagram pack.", stock_provider.ENTRY, stock_provider.save_key, "px")
    key_card("Claude (writing and planning)", "Required for every reel: it looks at your pictures, plans the story and writes the "
             "captions. Get a key at console.anthropic.com.", "anthropic",
             lambda v: keyring.set_password(SERVICE, "anthropic", v.strip()), "cl")
    section("System")
    with st.container(border=True):
        ok, detail = worker_state()
        a, b, c = st.columns([2, 1, 1])
        a.markdown(f"**Worker:** {'running' if ok else 'stopped'} ({detail})")
        if b.button("Start", use_container_width=True, key="sys_start"):
            start_worker()
            st.toast("Start requested.")
        if c.button("Stop", use_container_width=True, key="sys_stop"):
            stop_worker()
            st.toast("Stop requested.")
        if PUBLIC_URL:
            st.caption(f"Remote address (your devices only): {PUBLIC_URL}")
        import encoder
        st.caption(f"Video encoder: {encoder.label()}. A graphics card is used automatically when it matches the CPU's picture quality.")
        st.caption(f"Reels In: {REELS_IN}")
        st.caption(f"Reels Out: {REELS_OUT}")
    cleanup_section()


if page == "Create":
    create_tab()
elif page == "My reels":
    watch_for_changes()  # the page refreshes by itself when a reel starts, moves on or finishes
    reels_tab()
else:
    settings_tab()
footer()
