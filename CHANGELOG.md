# Buzz changelog

AI Reel Studio: reels from photos, videos or just an idea

## 2.1.0 (13 Nov 2026): Weekly reel limits and family defaults

- New weekly reel limit per person (Monday to Sunday), next to the daily limit.
- New family defaults in Settings: set the shared-key permission, monthly tokens, reels per day and reels per week once for everyone; individual settings replace them. People who match the defaults follow later changes.
- Each person's line in Usage and limits shows reels made today, this week and this month.
- Automated tests for the weekly limit and the defaults.

## 2.0.0 (12 Nov 2026): Linux, servers and several users

- Linux version: installer (install_linux.sh), uninstaller, systemd services with CPU and memory caps, nginx file with websocket support, server guide (docs/SERVER.md). Tested on Ubuntu 24.04 including a from-scratch install.
- Cross-platform code: encrypted secret store on Linux (Windows Credential Manager on Windows), picture drawing without a browser (resvg), free fonts bundled for Linux, worker control without Windows Task Scheduler.
- Per-user reels: members see only their own reels; the owner sees all.
- Per-user Claude keys, usage tracking (tokens only), per-person monthly token and daily reel limits, a studio monthly budget, optional cost estimates and a Pause AI for everyone switch.
- The free voice now runs in its own helper process, so its memory (about 1 GB) returns to the system after every reel; it restarts by itself if it ever stops.
- Line endings of scripts are fixed to Unix; automated tests for the per-user rules (tests/test_per_user.py).
- Server lifecycle verified on Ubuntu 24.04: services under a dedicated user restart within seconds after a crash and the interrupted reel resumes; the nginx proxy passes websockets; the uninstaller removes services and environment but keeps reels, accounts and keys.

## 1.0.9 (12 Nov 2026): README accuracy

- README: the Smart App Control section now states only what Microsoft documents (link added) and no longer mentions evaluation mode or planned signing.

## 1.0.8 (12 Nov 2026): Uninstaller

- New Uninstall Buzz.bat: removes the background tasks and the Python environment, and separately asks before removing saved keys or deleting the whole folder (reels and accounts are kept by default).
- README: clearer guidance for Windows 11 Smart App Control, without asking anyone to lower a security setting.

## 1.0.7 (12 Nov 2026): Key entry

- Saving the Claude key now checks it with Claude straight away: a wrong key is refused with a clear message and nothing is saved.
- After a key is saved the box clears and Save is greyed out until you type a new key, so it is obvious the key was stored.

## 1.0.6 (12 Nov 2026): Lighter Claude connection

- Buzz now talks to Claude directly through a small plain-Python client (claude_api.py) instead of the Anthropic SDK. This removes the SDK and its compiled helper (jiter), which Windows Smart App Control can block, so reels can be made on those PCs.
- Clearer messages when Claude refuses a key or cannot be reached; automatic retries when Claude is busy.

## 1.0.5 (12 Nov 2026): Installer window

- The installer window now closes by itself after a successful install, and waits for a key press only if something went wrong.

## 1.0.4 (12 Nov 2026): Smoother flow

- After you press Create or Upload, the page moves to My reels by itself and shows the new reel being prepared.
- README: a note for Windows 11 Smart App Control, which can block unsigned Python library files.

## 1.0.3 (12 Nov 2026): Installer fix

- Fixed the background-task step of the installer failing on some Windows setups (a PowerShell variable named args clashed with a built-in).
- The installer now keeps a log (Work\install.log) and, if anything fails, shows a clear message and waits instead of closing.

## 1.0.2 (12 Nov 2026): Key entry moved into the app

- The installer no longer asks for the Claude key. You add it on the Settings tab, and a banner reminds you until it is saved.
- README: how to get past Windows 11 Smart App Control (unblock the zip before extracting).

## 1.0.1 (12 Nov 2026): Install location

- The installer asks where to install (default: Documents\Buzz), copies Buzz there and sets everything up in that folder. No fixed paths are built in.
- Updating: run the new installer and choose the same folder; reels, accounts and settings are kept.

## 1.0.0 (12 Nov 2026): First public release

- Two modes in one app: reels from photos and videos, and reels from only an idea.
- AI understanding of every picture and clip, beat-matched cutting, face-safe text, collages for landscape pictures, optional portrait centring.
- Choose the opening and closing picture or clip; the story is built around them.
- Music: use your own song, or generate original music from up to three keywords, tuned to be clear on phone speakers.
- Voiceover: free local voice (Kokoro) or Google Cloud Text-to-Speech; background music ducks under the voice.
- Idea reels: ten colour themes; gradient, plain colour, drawn pictures or Pexels video backgrounds.
- Instagram pack: hook, caption, 5 hashtags, cover text, best time, alt text; download as text; readable file names.
- Reel length selector (15 to 90 s) and an assets selector (Auto, All, or a number).
- Change notes in plain words ('make shot 5 the opening', 'use a different font') and one-tap quick changes.
- Accounts with email and password, 30-day remember-me, forgot-password codes, owner and member roles.
- Settings: Claude key, free voice install, Google voice key, Pexels key, mail, system status, automatic cleanup.
- Safe uploads: file-type and content checks, size limits, no executable files.
- Live page: auto-refreshing lists and a smooth real-time progress bar.
- Automatic cleanup: reels older than 15 days move to a holding folder and are deleted 3 days later; Keep switch per reel.
- My reels shows the last 15 days.
- Video encoding uses an NVIDIA, Intel or AMD graphics card automatically when one is present and its quality at least matches the CPU encoder; otherwise the CPU.
- Windows installer (no administrator needed) that sets up Python, FFmpeg, the environment and two background tasks.

## Modules

- `worker.py / service_ctl.py`: Background worker: one job at a time, restarts itself; start and stop on any system
- `secrets_store.py`: Where keys are kept: Credential Manager on Windows, an encrypted file on Linux
- `usage.py`: Reel owners, per-user keys, usage tracking and limits
- `pipeline.py`: One folder of media to one finished reel
- `ingest.py`: Reads and catalogues photos and videos
- `music.py / music_provider.py`: Beat and energy analysis; original music generator
- `ai_plan.py`: AI understanding, story plan, asset count, opening and closing shot
- `render.py / encoder.py`: FFmpeg rendering, text, logo, audio mix; picks the CPU or a graphics-card video encoder by testing quality
- `layout.py / facedetect.py`: Keeps text clear of faces
- `revise.py`: Plain-language change notes
- `prompt_reel.py / art_provider.py`: Idea reels: script, scenes, themes, drawn pictures
- `claude_api.py`: Plain-Python Claude Messages client with retries
- `voice_provider.py / voice_worker.py / narration.py`: Kokoro (in its own helper process) and Google voices, voiceover timing
- `stock_provider.py`: Pexels stock video
- `social.py`: Instagram pack
- `progress.py`: Real-time progress
- `uploads.py`: Safe upload checks
- `auth.py / mailer.py`: Accounts, sessions, reset codes, optional email
- `cleanup.py`: Nightly tidy-up of old reels
- `app.py`: The web page

## Keys used (Windows Credential Manager, service `ai-reel-studio`)

- `anthropic`: Claude key (required)
- `google_tts`: Google Text-to-Speech key (optional)
- `pexels`: Pexels key (optional)
- `smtp`: Mail settings for reset codes (optional)

---
Built by Amit at https://nobrand.in - collaborator feetandpedals.com
