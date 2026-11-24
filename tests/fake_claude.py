"""A stand-in for the Claude API, for install tests on a server without spending tokens or needing a key.
Answers the idea-reel script and the Instagram pack with fixed, valid replies. Start it, then point Buzz at it:
    python tests/fake_claude.py 8765 &
    BUZZ_CLAUDE_URL=http://127.0.0.1:8765/v1/messages BUZZ_ANTHROPIC=test ...
Never use it for real reels: every reel gets the same script."""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT = {
    "title": "Morning rides matter",
    "look": "ocean",
    "mood": "upbeat",
    "scenes": [
        {"text": "Your best ride starts at dawn", "voiceover": "Your best ride of the week starts before the city wakes up.", "seconds": 4},
        {"text": "Empty roads, cool air", "voiceover": "The roads are empty and the air is cool, so every kilometre feels easier.", "seconds": 4.5},
        {"text": "Ride with friends", "voiceover": "Ride with friends and the early alarm stops feeling like a sacrifice.", "seconds": 4.5},
        {"text": "Coffee tastes better after", "voiceover": "And honestly, the coffee afterwards tastes better than any other cup of the day.", "seconds": 4.5},
        {"text": "Start small this weekend", "voiceover": "Start small this weekend with twenty easy kilometres and see how you feel.", "seconds": 4.5},
        {"text": "Your legs will thank you", "voiceover": "Your legs, your head and your whole week will thank you for it.", "seconds": 4},
    ],
    "cta": "Follow for weekend routes",
}
PACK = {"hook": "The best ride of your week starts at dawn", "caption": "Empty roads, cool air, good friends.\nWho is riding this weekend?",
        "hashtags": ["cycling", "morningride", "roadcycling", "cyclinglife", "weekendride"], "cover_text": "Ride at dawn",
        "best_time": "Saturday around 7 am.", "alt_text": "Text scenes about the joy of an early morning bike ride."}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        text = json.dumps(body.get("messages", []))
        reply = SCRIPT if "short vertical reels" in text else PACK if "social media editor" in text else {"ok": True}
        out = json.dumps({"content": [{"type": "text", "text": json.dumps(reply)}], "stop_reason": "end_turn",
                          "usage": {"input_tokens": 500, "output_tokens": 300}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), H).serve_forever()
