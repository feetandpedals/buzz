# Deploying Buzz on a shared Linux server

## What the server needs

- Linux x86-64 with SSH access and permission to keep programs running (a VPS, or a shared host that allows background processes). Web-only shared hosting (cPanel PHP plans) cannot run Buzz.
- `curl`, `tar` and `xz`. Python 3.11 to 3.13 is used if present; otherwise setup fetches a private Python. No root needed.
- About 4 GB of RAM free for Buzz, 2 CPU cores and 20 GB of disk. A 30-second voiced reel peaks at about 1.3 GB and takes about a minute on 2 cores.

## Install

```bash
git clone https://github.com/feetandpedals/buzz.git ~/buzz    # or unzip a release into ~/buzz
cd ~/buzz
./setup.sh
```

`setup.sh` installs Python packages, FFmpeg and the face detector inside the folder, creates `buzz.env`, and starts Buzz on `127.0.0.1:8501`. It uses systemd user services when the server has them, with the memory and CPU caps from `buzz.env`. Otherwise it starts Buzz as background processes and prints a one-line `@reboot` crontab entry.

On a server with systemd, ask an administrator to run this once so Buzz keeps running after you log out:

```bash
sudo loginctl enable-linger <your-user>
```

## Put it on your domain

1. Copy `deploy/nginx-buzz.conf` to the nginx sites folder, set `server_name`, enable it and reload nginx. It already has the websocket headers and long timeouts that Buzz needs.
2. Add HTTPS: `sudo certbot --nginx -d buzz.example.com`.
3. Open the site and create the owner account. The first person to open a fresh install becomes the owner, so do this right away.
4. On **Settings**, add the Claude key. For spoken voiceovers, press **Install the free voice**. It downloads the Kokoro model (about 350 MB), checks it, and can be resumed if the connection drops.

## Settings (`buzz.env`)

| Setting | Default | What it does |
|---|---|---|
| `BUZZ_HOST`, `BUZZ_PORT` | `127.0.0.1`, `8501` | Where the page listens. Keep it on 127.0.0.1 behind nginx. |
| `BUZZ_MAX_UPLOAD_MB` | `1500` | Largest upload. Keep nginx `client_max_body_size` at least this big. |
| `BUZZ_THREADS` | `2` | CPU threads one reel may use (encoding, voice, music). |
| `BUZZ_WORKER_MEMORY` | `3G` | Hard memory cap for rendering. Slow-down starts at 85% of it. |
| `BUZZ_WEB_MEMORY` | `1G` | Hard memory cap for the web page. |
| `BUZZ_CPU_QUOTA` | `200%` | CPU cap for rendering (100% is one core). |
| `BUZZ_SECRETS_DIR`, `BUZZ_MASTER_KEY` | not set | Where encrypted keys live, or the master key itself. |
| `BUZZ_ANTHROPIC` | not set | A studio Claude key, instead of saving one on Settings. |
| `BUZZ_CLAUDE_URL` | not set | Send Claude requests through a gateway. |

After a change, run `./setup.sh` again (to apply new caps to the services) or `./buzzctl.sh restart`.

Memory and CPU caps are enforced by systemd. They need cgroup v2, which is the default on Ubuntu 22.04 and later. Without systemd, Buzz still renders one reel at a time with the thread limit, and the free voice gives its memory back after every reel.

## Day to day

```bash
./buzzctl.sh status     # services, last worker check-in, page health
./buzzctl.sh restart
./buzzctl.sh logs
```

**Update:** `git pull` (or unzip the new version over the old folder), then `./setup.sh`. Reels, accounts, keys and `buzz.env` are kept.

**Back up:** the `Work/` folder (accounts, settings, usage), `buzz.env` and `~/.config/buzz/` (encrypted keys).

**Uninstall:** `./uninstall_linux.sh --dry-run` shows what it would do, and it asks before deleting any data.

## Check an install

After installing the free voice, this makes a 30-second voiced idea reel through the running worker and checks the result. It uses the studio's Claude key, so it costs a few cents.

```bash
.venv/bin/python tests/smoke_reel.py
```

To test without a key, start `tests/fake_claude.py` and point `BUZZ_CLAUDE_URL` at it. The script's docstring explains how.

The longer server guide, with sizing and troubleshooting, is `docs/SERVER.md`.
