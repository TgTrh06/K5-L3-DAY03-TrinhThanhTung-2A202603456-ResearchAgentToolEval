"""Unit test cho tool mới hn_top (Hacker News).

Toàn bộ request mạng được giả lập (monkeypatch requests.get) nên test chạy offline,
nhanh và không phụ thuộc dữ liệu HN thật.

Chạy:  pytest tests/test_hn_top.py -v
"""
import importlib

import pytest
import requests

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
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


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


@pytest.mark.parametrize("limit", [0, -1, 31, True, "5"])
def test_invalid_limit_returns_error_without_request(monkeypatch, limit):
    monkeypatch.setattr(hn_module.requests, "get", lambda *args, **kwargs: pytest.fail("unexpected request"))
    result = hn_top(limit=limit)
    assert result["error"] == "ValueError"
    assert "limit" in result["message"]


def test_invalid_story_type_returns_error_without_request(monkeypatch):
    monkeypatch.setattr(hn_module.requests, "get", lambda *args, **kwargs: pytest.fail("unexpected request"))
    result = hn_top(story_type="../../admin")
    assert result["error"] == "ValueError"
    assert "story_type" in result["message"]


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


def test_http_error_returns_error_dict(monkeypatch):
    monkeypatch.setattr(hn_module.requests, "get", lambda *args, **kwargs: FakeResponse({}, status_code=503))
    result = hn_top()
    assert result["tool"] == "hn_top"
    assert result["error"] == "HTTPError"
    assert "503" in result["message"]


def test_timeout_returns_error_dict(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout("request timed out")

    monkeypatch.setattr(hn_module.requests, "get", timeout)
    result = hn_top()
    assert result["error"] == "Timeout"
    assert result["message"] == "request timed out"


def test_unexpected_stories_response_returns_error_dict(monkeypatch):
    monkeypatch.setattr(hn_module.requests, "get", lambda *args, **kwargs: FakeResponse({"error": "bad response"}))
    result = hn_top()
    assert result["error"] == "ValueError"
    assert "must be a list" in result["message"]
