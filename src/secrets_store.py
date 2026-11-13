"""Where Buzz keeps its secrets (API keys, mail settings). Never in code, never in the project folder.
- Windows: Windows Credential Manager (through the keyring library), as before.
- Linux / servers: one encrypted file (Fernet) in the service user's config folder, mode 0600. The master key comes from the
  BUZZ_MASTER_KEY environment variable when set (for example from a systemd credential); otherwise it is generated once into
  a separate 0600 file next to the encrypted file. Setting BUZZ_SECRETS_DIR moves both.
- Any secret can also be supplied as an environment variable named BUZZ_<NAME> (for example BUZZ_ANTHROPIC) which wins over the store.
Same three functions on every platform: get_password, set_password, delete_password."""
import json
import os
import sys
import tempfile
from pathlib import Path

WINDOWS = sys.platform == "win32"
WHERE = "Windows Credential Manager" if WINDOWS else "an encrypted file on this server"

if WINDOWS:
    import keyring as _keyring


def _dir():
    base = os.environ.get("BUZZ_SECRETS_DIR")
    d = Path(base) if base else Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "buzz"
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def _fernet():
    from cryptography.fernet import Fernet
    env = os.environ.get("BUZZ_MASTER_KEY")
    if env:
        return Fernet(env.encode())
    kf = _dir() / "master.key"
    if not kf.exists():
        fd = os.open(str(kf), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(Fernet.generate_key())
    return Fernet(kf.read_bytes().strip())


def _load():
    f = _dir() / "secrets.enc"
    if not f.exists():
        return {}
    try:
        return json.loads(_fernet().decrypt(f.read_bytes()).decode("utf-8"))
    except Exception:
        return {}


def _save(data):
    f = _dir() / "secrets.enc"
    blob = _fernet().encrypt(json.dumps(data).encode("utf-8"))
    fd, tmp = tempfile.mkstemp(dir=str(_dir()))
    with os.fdopen(fd, "wb") as t:
        t.write(blob)
    os.chmod(tmp, 0o600)
    os.replace(tmp, f)


def _env_name(name):
    return "BUZZ_" + "".join(c if c.isalnum() else "_" for c in name).upper()


def get_password(service, name):
    v = os.environ.get(_env_name(name))
    if v:
        return v
    if WINDOWS:
        return _keyring.get_password(service, name)
    return _load().get(service, {}).get(name)


def set_password(service, name, value):
    if WINDOWS:
        return _keyring.set_password(service, name, value)
    data = _load()
    data.setdefault(service, {})[name] = value
    _save(data)


def delete_password(service, name):
    if WINDOWS:
        return _keyring.delete_password(service, name)
    data = _load()
    if data.get(service, {}).pop(name, None) is not None:
        _save(data)
