# Buzz changelog

AI Reel Studio: reels from photos, videos or just an idea

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

- `worker.py`: Background worker: one job at a time, restarts itself
- `pipeline.py`: One folder of media to one finished reel
- `ingest.py`: Reads and catalogues photos and videos
- `music.py / music_provider.py`: Beat and energy analysis; original music generator
- `ai_plan.py`: AI understanding, story plan, asset count, opening and closing shot
- `render.py / encoder.py`: FFmpeg rendering, text, logo, audio mix; picks the CPU or a graphics-card video encoder by testing quality
- `layout.py / facedetect.py`: Keeps text clear of faces
- `revise.py`: Plain-language change notes
- `prompt_reel.py / art_provider.py`: Idea reels: script, scenes, themes, drawn pictures
- `voice_provider.py / narration.py`: Kokoro and Google voices, voiceover timing
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
