# Running Buzz on a Linux server

Buzz runs as two small programs: a **web page** (Streamlit, listens on 127.0.0.1:8501 only) and a **worker** that renders one reel at a time.
Put nginx in front of the page for outside access. Tested on Ubuntu 24.04 (x86-64).

## Sizing

| | Minimum | Comfortable |
|---|---|---|
| CPU | 2 cores | 4 cores |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 50-100 GB |

- Reels render one at a time and use most cores for a few minutes each; more cores means faster reels.
- The free voice (Kokoro) needs about 1 GB extra while a reel is being voiced. It runs in its own short-lived helper process, so the memory returns to the system when the reel is done.
- Each finished reel takes roughly 5 to 60 MB; reels older than 15 days are cleaned up nightly (a Keep switch protects any reel).
- No GPU is used.

## Install (as a normal user, no root needed)

1. Copy or unzip Buzz into the service user's home, for example `~/buzz`.
2. `./install_linux.sh` - sets up Python 3.12, a full FFmpeg (with the text filter), the Python environment and the face detector, all inside the folder.
   If the machine has no Python 3.11 to 3.13, the script fetches a private Python with `uv`. It only downloads what is missing.
3. `./deploy/install-services.sh` - installs and starts the two systemd user services, with CPU and memory caps (edit `deploy/*.service` first to change them).
   Once, as an administrator: `sudo loginctl enable-linger <user>` so the services keep running after logout.
4. nginx: copy `deploy/nginx-buzz.conf` to `/etc/nginx/sites-available/`, set your domain, enable it, then add HTTPS with certbot.
   The page needs websocket headers and long timeouts; the file already has them.
5. Open the site, create the **owner account**, then add your Claude key on the **Settings** tab.

## Keys and secrets

- Keys are stored **encrypted** in `~/.config/buzz/secrets.enc` (mode 0600). The master key is generated once into `~/.config/buzz/master.key` (mode 0600),
  or supplied through the `BUZZ_MASTER_KEY` environment variable (for example from a systemd credential). Nothing is kept in the Buzz folder or in git.
- Move the secrets folder with `BUZZ_SECRETS_DIR`. Any secret can also be given as an environment variable named `BUZZ_<NAME>`, for example `BUZZ_ANTHROPIC`.
- Back up `~/.config/buzz/` together with the Buzz folder's `Work/` (accounts, settings) if you want a restorable copy.

## People, keys and limits

- Every reel belongs to the person who made it; members see only their own reels, the owner sees all.
- Each person can add their **own Claude key** (Settings), so their reels are paid by their own account.
- The owner decides who may use the shared studio key, and sets per-person monthly token and daily reel limits, a studio-wide monthly budget and optional prices for cost estimates.
  A **Pause AI for everyone** switch stops all shared-key use at once. Usage is kept as token counts only (`Work/usage.jsonl`), never prompts or keys.

## Update

Unpack the new version over the old folder (keep `Work/`, `Reels In`, `Reels Out`), run `./install_linux.sh` again, then `systemctl --user restart buzz-worker buzz-web`.

## Uninstall

`./uninstall_linux.sh --dry-run` shows what would happen. `./uninstall_linux.sh` removes the services and Python environment, and asks separately before deleting the encrypted keys or the whole folder with your reels.

## Troubleshooting

- *The page loads but reels never start:* check `systemctl --user status buzz-worker` and `Work/logs/worker.log`.
- *"ffmpeg not found":* run `./install_linux.sh` again; Buzz looks in `./bin`, `~/.local/bin` and `/usr/local/bin`.
- *Text missing in videos:* the FFmpeg must have the `drawtext` filter; the installer checks for it and downloads a full build if needed.
- *Page stuck on "connecting":* nginx is missing the websocket headers; use `deploy/nginx-buzz.conf`.
