import requests

HN_API = "https://hacker-news.firebaseio.com/v0"

def hn_top(story_type: str = "top", query: str = "", limit: int = 5) -> dict:
    ids = requests.get(f"{HN_API}/{story_type}stories.json", timeout=10).json()
    items = []
    for story_id in ids[:30]:
        it = requests.get(f"{HN_API}/item/{story_id}.json", timeout=10).json() or {}
        title = it.get("title", "")
        if query and query.lower() not in title.lower():
            continue
        items.append({
            "title": title,
            "url": it.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
            "source": "Hacker News",
            "score": it.get("score", 0),
        })
        if len(items) >= limit:
            break
    return {"items": items}