"""A tiny Claude Messages API client in plain Python (standard library only).
Buzz needs just one call, so it does not use the Anthropic SDK. That keeps installs light and avoids compiled
dependencies that some Windows security policies (Smart App Control) block."""
import json
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

URL = "https://api.anthropic.com/v1/messages"
VERSION = "2023-06-01"


class ClaudeError(RuntimeError):
    pass


class _Messages:
    def __init__(self, key, before=None, on_usage=None):
        self._key = key
        self._before, self._on_usage = before, on_usage

    def create(self, model, max_tokens, messages, **extra):
        if self._before:
            self._before()  # limits are checked before every request
        body = json.dumps({"model": model, "max_tokens": max_tokens, "messages": messages, **extra}).encode("utf-8")
        headers = {"x-api-key": self._key, "anthropic-version": VERSION, "content-type": "application/json"}
        last = None
        for attempt in range(5):
            req = urllib.request.Request(URL, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
                except Exception:
                    pass
                last = ClaudeError(f"Claude refused the request ({e.code}). {detail[:200]}".strip())
                if e.code == 401:
                    raise ClaudeError("Claude did not accept the key. Check it on the Settings tab.") from None
                if e.code not in (408, 409, 429, 500, 502, 503, 504, 529):
                    raise last from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = ClaudeError(f"Could not reach Claude ({e}). Check the internet connection.")
            time.sleep(min(2 ** attempt * 2, 30))
        else:
            raise last
        if self._on_usage:
            try:
                self._on_usage(model, data.get("usage"))
            except Exception:
                pass
        blocks = [SimpleNamespace(type=b.get("type"), text=b.get("text", "")) for b in data.get("content", [])]
        return SimpleNamespace(content=blocks, stop_reason=data.get("stop_reason"), usage=data.get("usage"))


class Client:
    def __init__(self, api_key, before=None, on_usage=None):
        self.messages = _Messages(api_key, before, on_usage)
