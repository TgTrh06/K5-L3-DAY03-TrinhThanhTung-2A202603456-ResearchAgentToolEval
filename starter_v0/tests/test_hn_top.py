"""Unit test cho tool mới hn_top (Hacker News).

Toàn bộ request mạng được giả lập (monkeypatch requests.get) nên test chạy offline,
nhanh và không phụ thuộc dữ liệu HN thật.

Chạy:  pytest tests/test_hn_top.py -v
"""
import importlib

import pytest

from tools import TOOL_FUNCTIONS
from tools.hn_top import hn_top

# Lấy đúng MODULE tools/hn_top.py. Không dùng `import tools.hn_top as ...` vì trong
# tools/__init__.py dòng `from .hn_top import hn_top` khiến tools.hn_top trỏ tới HÀM.
hn_module = importlib.import_module("tools.hn_top")

# Dữ liệu giả: id -> item. Item 3 cố ý không có "url" để test link dự phòng.
FAKE_ITEMS = {
    1: {"title": "New AI model released", "url": "https://example.com/ai", "score": 300},
    2: {"title": "Rust 2.0 is out", "url": "https://example.com/rust", "score": 200},
    3: {"title": "Ask HN: AI tools you use?", "score": 150},
    4: {"title": "Open-source AI agents", "url": "https://example.com/agents", "score": 120},
}


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


@pytest.fixture
def fake_hn(monkeypatch):
    """Thay requests.get bằng hàm giả; trả về list URL đã được gọi để kiểm tra."""
    called_urls = []

    def fake_get(url, timeout=10, **kwargs):
        called_urls.append(url)
        if url.endswith("stories.json"):
            return FakeResponse(list(FAKE_ITEMS))
        story_id = int(url.rsplit("/", 1)[-1].removesuffix(".json"))
        return FakeResponse(FAKE_ITEMS.get(story_id))

    monkeypatch.setattr(hn_module.requests, "get", fake_get)
    return called_urls


# ---------- Đăng ký tool ----------

def test_registered_in_tool_functions():
    assert TOOL_FUNCTIONS.get("hn_top") is hn_top


# ---------- Định dạng kết quả ----------

def test_result_shape(fake_hn):
    result = hn_top()
    assert isinstance(result, dict) and isinstance(result["items"], list)
    for item in result["items"]:
        assert set(item) == {"title", "url", "source", "score"}
        assert item["source"] == "Hacker News"


def test_default_limit_is_5_or_less(fake_hn):
    assert len(hn_top()["items"]) <= 5


# ---------- Tham số ----------

@pytest.mark.parametrize("limit", [1, 2, 3])
def test_limit_is_respected(fake_hn, limit):
    assert len(hn_top(limit=limit)["items"]) == limit


def test_query_filters_title_case_insensitive(fake_hn):
    titles = [i["title"] for i in hn_top(query="ai", limit=10)["items"]]
    assert titles == [
        "New AI model released",
        "Ask HN: AI tools you use?",
        "Open-source AI agents",
    ]


def test_empty_query_returns_all(fake_hn):
    assert len(hn_top(query="", limit=10)["items"]) == len(FAKE_ITEMS)


@pytest.mark.parametrize("story_type", ["top", "new", "best"])
def test_story_type_selects_endpoint(fake_hn, story_type):
    hn_top(story_type=story_type, limit=1)
    assert fake_hn[0].endswith(f"/{story_type}stories.json")


# ---------- Trường hợp biên ----------

def test_missing_url_falls_back_to_hn_link(fake_hn):
    items = hn_top(query="Ask HN")["items"]
    assert items[0]["url"] == "https://news.ycombinator.com/item?id=3"


def test_no_match_returns_empty_list(fake_hn):
    assert hn_top(query="blockchain") == {"items": []}


def test_stops_fetching_after_limit(fake_hn):
    hn_top(limit=1)
    # 1 request lấy danh sách id + 1 request lấy item đầu tiên
    assert len(fake_hn) == 2