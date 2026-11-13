"""Phone alerts through ntfy.sh. The topic name is the secret, so it lives in Windows Credential Manager.
Messages carry only the reel's folder name and a status, never file paths or media."""
import secrets
import urllib.request

import secrets_store as vault

SERVICE = "ai-reel-studio"
SERVER = "https://ntfy.sh"


def topic(create=False):
    t = vault.get_password(SERVICE, "ntfy_topic")
    if not t and create:
        t = "reel-studio-" + secrets.token_urlsafe(9).replace("_", "x").replace("-", "y").lower()
        vault.set_password(SERVICE, "ntfy_topic", t)
    return t


def send(title, message, tags="clapper", priority="default"):
    """Never raises: a failed alert must not break a render."""
    try:
        t = topic()
        if not t:
            return False
        req = urllib.request.Request(f"{SERVER}/{t}", data=message.encode("utf-8"), method="POST",
                                     headers={"Title": title.encode("ascii", "replace").decode(),
                                              "Tags": tags, "Priority": priority})
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception:
        return False
