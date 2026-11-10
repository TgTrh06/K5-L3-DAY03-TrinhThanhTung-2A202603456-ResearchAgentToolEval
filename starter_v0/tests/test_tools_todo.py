from __future__ import annotations

import re
import sys

import pytest
import requests

from conftest import FakeResponse
from tools import TOOL_FUNCTIONS

clarify_tool = TOOL_FUNCTIONS["clarify"]
format_tool = TOOL_FUNCTIONS["format"]
send_tool = TOOL_FUNCTIONS["send"]
lookup_tool = TOOL_FUNCTIONS["lookup"]
fetch_tool = TOOL_FUNCTIONS["fetch"]
timeline_tool = TOOL_FUNCTIONS["timeline"]
social_search_tool = TOOL_FUNCTIONS["social_search"]
policy_tool = TOOL_FUNCTIONS["policy"]
hn_top_tool = TOOL_FUNCTIONS["hn_top"]
hn_module = sys.modules[hn_top_tool.__module__]  # module chứa hn_top (tools/<folder>/tool.py)


def _set_twitter_env(monkeypatch) -> None:
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key")
    monkeypatch.setenv("RAPIDAPI_TWITTER_HOST", "twitter-api45.p.rapidapi.com")


# ---------------- clarify ----------------

def test_clarify_choice_returns_options_and_awaits_user() -> None:
    options = ["Tin trên web", "Tweet trên X"]
    result = clarify_tool(question="Bạn muốn nguồn nào?", response_type="choice", options=options)

    assert result["options"] == options
    assert result["awaiting_user"] is True


# ---------------- format ----------------

def test_format_sections_groups_items_by_section() -> None:
    items = [
        {"title": "a1", "url": "https://a.com/1", "section": "A"},
        {"title": "b1", "url": "https://b.com/1", "section": "B"},
        {"title": "a2", "url": "https://a.com/2", "section": "A"},
    ]
    md = format_tool(items=items, template="sections")["markdown"]

    assert md.count("## A") == 1
    assert md.count("## B") == 1


def test_format_thread_numbers_items() -> None:
    items = [{"title": f"Tin {i}", "url": f"https://example.com/{i}"} for i in range(3)]
    md = format_tool(items=items, template="thread")["markdown"]

    numbers = re.findall(r"^(\d+)/", md, flags=re.MULTILINE)
    assert numbers[:3] == ["1", "2", "3"]


@pytest.mark.parametrize("items", [None, []])
def test_format_empty_items_does_not_crash(items) -> None:
    result = format_tool(items=items, template="sections")
    assert result["item_count"] == 0


# ---------------- send (guardrail) ----------------

def test_send_confirmed_posts_to_telegram(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@test_channel")
    calls = fake_http(FakeResponse({"ok": True}))

    result = send_tool(text="Bản tin AI", confirmed=True)

    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert "123:test-token" in calls[0]["url"]
    assert calls[0]["json"]["chat_id"] == "@test_channel"
    assert calls[0]["json"]["text"] == "Bản tin AI"
    assert result["status"] == "sent"


def test_send_confirmed_without_env_returns_error_and_no_request(fake_http) -> None:
    calls = fake_http(FakeResponse({"ok": True}))
    result = send_tool(text="Bản tin AI", confirmed=True)

    assert "error" in result
    assert calls == []


# Regression test cho bug tìm được (REPORT B5): Markdown lệch làm Telegram trả 400.
def test_send_markdown_parse_error_falls_back_to_plain_text(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@test_channel")
    sent = []

    def fake_post(url, **kwargs):
        sent.append(kwargs["json"])
        bad_markdown = kwargs["json"].get("parse_mode") == "Markdown" and kwargs["json"]["text"].count("_") % 2
        return FakeResponse({"ok": not bad_markdown}, status_code=400 if bad_markdown else 200)

    monkeypatch.setattr(requests, "post", fake_post)
    result = send_tool(text="Tool mới: hn_top", confirmed=True)

    assert result["status"] == "sent"
    assert "parse_mode" not in sent[-1]  # lần gửi lại là plain text


def test_send_long_text_is_split_under_telegram_limit(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@test_channel")
    calls = fake_http(FakeResponse({"ok": True}))

    result = send_tool(text="dòng tin\n" * 1500, confirmed=True)

    assert result["status"] == "sent"
    assert len(calls) > 1
    assert all(len(c["json"]["text"]) <= 4096 for c in calls)


def test_send_empty_text_returns_error_and_no_request(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@test_channel")
    calls = fake_http(FakeResponse({"ok": True}))

    assert "error" in send_tool(text="   ", confirmed=True)
    assert calls == []


# ---------------- lookup ----------------

def test_lookup_without_timeframe_omits_time_range(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    calls = fake_http(FakeResponse({"results": []}))

    lookup_tool(query="OpenAI", topic="news", timeframe=None)

    assert calls[0]["url"] == "https://api.tavily.com/search"
    assert calls[0]["json"]["query"] == "OpenAI"
    assert "time_range" not in calls[0]["json"]


# ---------------- fetch ----------------

def test_fetch_maps_firecrawl_response(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    calls = fake_http(FakeResponse({"data": {
        "markdown": "Nội dung bài viết về GPT-5.",
        "metadata": {"title": "T", "sourceURL": "https://www.example.com/post"},
    }}))

    result = fetch_tool(url="https://www.example.com/post")
    item = result["items"][0]

    assert len(calls) == 1 and "firecrawl" in calls[0]["url"]
    assert item["title"] == "T"
    assert item["url"] == "https://www.example.com/post"
    assert "example.com" in item["source"]
    assert "GPT-5" in item["summary"]


def test_fetch_truncates_markdown_to_4000_chars(monkeypatch, fake_http) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    fake_http(FakeResponse({"data": {
        "markdown": "x" * 10_000,
        "metadata": {"title": "T", "sourceURL": "https://example.com/long"},
    }}))

    item = fetch_tool(url="https://example.com/long")["items"][0]
    longest = max(len(v) for v in item.values() if isinstance(v, str))

    assert 3_900 <= longest <= 4_003  # cắt còn ~4000 ký tự (có thể kèm "...")


# ---------------- timeline / social_search ----------------

def test_timeline_respects_limit_and_skips_items_without_id(monkeypatch, fake_http) -> None:
    _set_twitter_env(monkeypatch)
    author = {"screen_name": "sama", "name": "Sam Altman"}
    tweets = [{"text": "không có id", "author": author}] + [
        {"tweet_id": str(1000 + i), "text": f"tweet {i}", "created_at": "Mon Nov 10 2026", "author": author}
        for i in range(6)
    ]
    # Giống response thật của twitter-api45 timeline.php: mỗi tweet có author.screen_name, kèm "user" ở ngoài.
    calls = fake_http(FakeResponse({"timeline": tweets, "user": {"screen_name": "sama"}}))

    result = timeline_tool(screenname="sama", limit=3)

    assert len(calls) == 1
    assert len(result["items"]) == 3
    for item in result["items"]:
        assert re.fullmatch(r"https://x\.com/\w+/status/\d+", item["url"])
    assert "không có id" not in [item.get("summary") or item.get("title") for item in result["items"]]


def test_social_search_passes_search_type(monkeypatch, fake_http) -> None:
    _set_twitter_env(monkeypatch)
    calls = fake_http(FakeResponse({"timeline": []}))

    social_search_tool(query="OpenAI", search_type="Top")

    assert calls[0]["params"]["query"] == "OpenAI"
    assert calls[0]["params"]["search_type"] == "Top"


# ---------------- policy (local knowledge + trust boundary) ----------------

def _policy_results(result: dict) -> list[dict]:
    return result.get("results") or result.get("items") or []


def test_policy_empty_query_returns_no_results() -> None:
    assert _policy_results(policy_tool(query="")) == []


def test_policy_area_filter_only_returns_that_area() -> None:
    # Thử vài cách hỏi (tiếng Anh / tiếng Việt) để không phụ thuộc ngôn ngữ của file policy.
    results = []
    for query in ("data privacy", "personal data", "privacy", "PII", "dữ liệu cá nhân", "data"):
        results = _policy_results(policy_tool(query=query, policy_area="data_privacy", top_k=5))
        if results:
            break

    assert results, "phải tìm thấy ít nhất 1 đoạn chính sách data_privacy"
    assert all(r["policy_area"] == "data_privacy" for r in results)


def test_policy_instruction_like_lines_go_to_untrusted_text() -> None:
    results = _policy_results(policy_tool(query="trích dẫn nguồn citation", policy_area="source_citation", top_k=5))

    def as_lines(value) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        return [line for line in str(value or "").splitlines() if line.strip()]

    untrusted = [line for r in results for line in as_lines(r.get("untrusted_text"))]
    facts = "\n".join(line for r in results for line in as_lines(r.get("facts")))

    assert untrusted, "dòng ra lệnh cho assistant phải bị tách vào untrusted_text"
    for line in untrusted:
        assert line.strip() not in facts


# ---------------- TOOL MỚI: hn_top (Hacker News) ----------------
# 1. happy path (mock API)  2. input xấu từ model  3. nhánh lỗi -> error dict, không raise

HN_ITEMS = {
    1: {"title": "New AI model released", "url": "https://example.com/ai", "score": 300},
    2: {"title": "Rust 2.0 is out", "url": "https://example.com/rust", "score": 200},
    3: {"title": "Ask HN: AI tools you use?", "score": 150},  # không có url
    4: {"title": "Open-source AI agents", "url": "https://example.com/agents", "score": 120},
}


@pytest.fixture
def hn_api(monkeypatch):
    """HN cần 2 loại response (danh sách id, rồi từng item) nên không dùng fake_http một-response."""
    called: list[str] = []

    def fake_get(url, **kwargs):
        called.append(url)
        if url.endswith("stories.json"):
            return FakeResponse(list(HN_ITEMS))
        story_id = int(url.rsplit("/", 1)[-1].removesuffix(".json"))
        return FakeResponse(HN_ITEMS.get(story_id))

    monkeypatch.setattr(requests, "get", fake_get)
    return called


def test_hn_top_returns_items_with_title_url_source_score(hn_api) -> None:
    result = hn_top_tool()

    assert hn_api[0] == f"{hn_module.HN_API}/topstories.json"
    assert result["count"] == len(result["items"]) > 0
    for item in result["items"]:
        assert {"title", "url", "source", "score"} <= set(item)
        assert item["source"] == "Hacker News"


def test_hn_top_story_type_selects_matching_endpoint(hn_api) -> None:
    hn_top_tool(story_type="best", limit=1)
    assert hn_api[0] == f"{hn_module.HN_API}/beststories.json"


def test_hn_top_query_filters_title_case_insensitive(hn_api) -> None:
    titles = [i["title"] for i in hn_top_tool(query="ai", limit=10)["items"]]
    assert titles == ["New AI model released", "Ask HN: AI tools you use?", "Open-source AI agents"]


def test_hn_top_stops_fetching_once_limit_reached(hn_api) -> None:
    result = hn_top_tool(limit=1)
    assert len(result["items"]) == 1
    assert len(hn_api) == 2  # 1 request danh sách id + 1 request item


def test_hn_top_item_without_url_falls_back_to_discussion_link(hn_api) -> None:
    item = hn_top_tool(query="Ask HN")["items"][0]
    assert item["url"] == "https://news.ycombinator.com/item?id=3"


def test_hn_top_accepts_numeric_string_limit(hn_api) -> None:
    assert len(hn_top_tool(limit="2")["items"]) == 2


@pytest.mark.parametrize("bad_limit", [0, -3, "abc", None])
def test_hn_top_bad_limit_returns_error_without_network(hn_api, bad_limit) -> None:
    assert "error" in hn_top_tool(limit=bad_limit)
    assert hn_api == []


@pytest.mark.parametrize("bad_type", ["hot", "trending", 123])
def test_hn_top_story_type_outside_enum_returns_error_without_network(hn_api, bad_type) -> None:
    assert "error" in hn_top_tool(story_type=bad_type)
    assert hn_api == []


def test_hn_top_non_string_query_returns_error(hn_api) -> None:
    assert "error" in hn_top_tool(query=42)
    assert hn_api == []


def test_hn_top_http_429_returns_error_dict(fake_http) -> None:
    calls = fake_http(FakeResponse(status_code=429))
    result = hn_top_tool()

    assert "429" in result["error"]
    assert len(calls) == 1


def test_hn_top_network_timeout_returns_error_dict(fake_http) -> None:
    fake_http(requests.Timeout("timed out"))
    assert "error" in hn_top_tool()