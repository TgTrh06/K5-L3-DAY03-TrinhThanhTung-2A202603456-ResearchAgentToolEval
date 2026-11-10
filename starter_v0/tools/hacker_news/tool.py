"""hn_top — lấy bài đang hot trên Hacker News (API công khai, không cần key).

Mọi lỗi (input xấu từ model, lỗi mạng, HTTP lỗi, JSON hỏng) đều trả về
{"error": "..."} thay vì raise, để agent đọc được và xử lý tiếp.
"""
import requests

HN_API = "https://hacker-news.firebaseio.com/v0"
VALID_STORY_TYPES = ("top", "new", "best")
MAX_LIMIT = 30   # chặn trên để không gọi API quá nhiều
SCAN_SIZE = 60   # số id tối đa quét khi lọc theo query
TIMEOUT = 10


def hn_top(story_type: str = "top", query: str = "", limit: int = 5) -> dict:
    # ---- Chuẩn hoá & kiểm tra input từ model ----
    story_type = (story_type or "top")
    if not isinstance(story_type, str) or story_type.strip().lower() not in VALID_STORY_TYPES:
        return {"error": f"story_type không hợp lệ: {story_type!r}. Chỉ nhận {list(VALID_STORY_TYPES)}."}
    story_type = story_type.strip().lower()

    try:
        limit = int(limit)  # model hay gửi "5" dạng chuỗi
    except (TypeError, ValueError):
        return {"error": f"limit phải là số nguyên, nhận được {limit!r}."}
    if limit <= 0:
        return {"error": f"limit phải >= 1, nhận được {limit}."}
    limit = min(limit, MAX_LIMIT)

    if query is None:
        query = ""
    if not isinstance(query, str):
        return {"error": f"query phải là chuỗi, nhận được {type(query).__name__}."}
    needle = query.strip().lower()

    # ---- Gọi API ----
    try:
        resp = requests.get(f"{HN_API}/{story_type}stories.json", timeout=TIMEOUT)
        resp.raise_for_status()
        ids = resp.json() or []

        items = []
        for story_id in ids[:SCAN_SIZE]:
            r = requests.get(f"{HN_API}/item/{story_id}.json", timeout=TIMEOUT)
            r.raise_for_status()
            it = r.json() or {}
            title = it.get("title") or ""
            if not title:
                continue
            if needle and needle not in title.lower():
                continue
            items.append({
                "title": title,
                "url": it.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                "source": "Hacker News",
                "score": it.get("score", 0),
            })
            if len(items) >= limit:
                break
    except requests.RequestException as exc:
        return {"error": f"Lỗi khi gọi Hacker News API: {exc}"}
    except ValueError as exc:  # JSON hỏng
        return {"error": f"Hacker News trả về dữ liệu không đọc được: {exc}"}

    return {"items": items, "story_type": story_type, "query": query, "count": len(items)}