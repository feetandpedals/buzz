"""Instagram pack: hook, caption, hashtags and posting tips for a finished reel (text only, one AI call)."""
import json
from pathlib import Path

import ai_plan

MAX_TAGS = 5  # Instagram allows five hashtags at most

PACK_PROMPT = """You are a social media editor for Instagram Reels. Write the posting pack for this finished reel.
Reel concept: %s
Title on screen: %r
Closing text: %r
Captions on screen: %s
Owner's brief: %s
Language: English only.

Reply with JSON only:
{"hook": str (first line of the post, under 80 characters, makes people stop scrolling),
 "caption": str (2 to 4 short lines, warm and natural, ends with a question or call to comment, no hashtags in it),
 "hashtags": [EXACTLY 5 strings without the # sign, the best five for reach and relevance: about 2 broad, 2 niche, 1 local or branded],
 "cover_text": str (3 to 5 words for the cover image),
 "best_time": str (one sentence on when to post),
 "alt_text": str (one sentence describing the reel for accessibility)}
Never invent facts, names or places that are not in the material above."""


def make_pack(plan, brief, out_dir):
    """Writes instagram.json and instagram.txt next to the reel. Never raises: a missing pack must not fail a reel."""
    out_dir = Path(out_dir)
    try:
        caps = "; ".join(s["caption"] for s in plan["shots"] if s.get("caption")) or "none"
        pack = ai_plan._ask(ai_plan.client(), [{"type": "text", "text": PACK_PROMPT % (
            plan.get("concept"), plan.get("title"), plan.get("closing"), caps, brief or "none")}], max_tokens=2000)
        tags = ["#" + t.lstrip("#").replace(" ", "") for t in pack.get("hashtags", [])][:MAX_TAGS]
        pack["hashtags"] = tags
        pack["credits"] = plan.get("credits") or []
        (out_dir / "instagram.json").write_text(json.dumps(pack, indent=1, ensure_ascii=False), encoding="utf-8")
        (out_dir / "instagram.txt").write_text(
            f"{pack.get('hook', '')}\n\n{pack.get('caption', '')}\n\n{' '.join(tags)}\n\n"
            f"Cover text: {pack.get('cover_text', '')}\nBest time to post: {pack.get('best_time', '')}\n"
            f"Alt text: {pack.get('alt_text', '')}\n" + "".join(f"Credit: {c}\n" for c in pack["credits"]),
            encoding="utf-8")
        return pack
    except Exception as e:
        (out_dir / "instagram_error.log").write_text(str(e), encoding="utf-8")
        return None
