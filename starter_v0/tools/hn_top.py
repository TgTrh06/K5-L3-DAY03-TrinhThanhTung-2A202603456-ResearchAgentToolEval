from typing import Any

import requests

from tools._shared import err

HN_API = "https://hacker-news.firebaseio.com/v0"

def hn_top(story_type: str = "top", query: str = "", limit: int = 5) -> dict[str, Any]:
    if not isinstance(story_type, str) or story_type not in {"top", "new", "best"}:
        return err("hn_top", ValueError("story_type must be one of: top, new, best"))
    if not isinstance(query, str):
        return err("hn_top", TypeError("query must be a string"))
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        return err("hn_top", ValueError("limit must be an integer from 1 to 30"))

    try:
        response = requests.get(f"{HN_API}/{story_type}stories.json", timeout=10)
        response.raise_for_status()
        ids = response.json()
        if not isinstance(ids, list):
            raise ValueError("Hacker News stories response must be a list")

        items = []
        for story_id in ids[:30]:
            response = requests.get(f"{HN_API}/item/{story_id}.json", timeout=10)
            response.raise_for_status()
            story = response.json() or {}
            if not isinstance(story, dict):
                continue
            title = story.get("title", "")
            if not isinstance(title, str) or (query and query.casefold() not in title.casefold()):
                continue
            items.append({
                "title": title,
                "url": story.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                "source": "Hacker News",
                "score": story.get("score", 0),
            })
            if len(items) >= limit:
                break
        return {"items": items}
    except Exception as exc:
        return err("hn_top", exc)
