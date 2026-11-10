from __future__ import annotations

import os
from typing import Any

import requests

from tools._shared import TIMEOUT, err

TELEGRAM_MAX_CHARS = 4096  # giới hạn 1 tin nhắn Telegram


def _chunks(text: str, size: int = 4000) -> list[str]:
    """Cắt văn bản dài thành nhiều tin, ưu tiên cắt ở chỗ xuống dòng."""
    parts: list[str] = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        cut = cut if cut > size // 2 else size
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return parts


def send_telegram(text: str = "", confirmed: bool = False) -> dict[str, Any]:
    # Guardrail: KHÔNG gọi mạng khi chưa có xác nhận của người dùng.
    if not confirmed:
        return {
            "tool": "send_telegram",
            "status": "needs_confirmation",
            "message": "Only send after the user explicitly confirms.",
        }
    if not isinstance(text, str) or not text.strip():
        return {"tool": "send_telegram", "status": "error", "error": "empty_text",
                "message": "Nội dung gửi đang rỗng."}
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise RuntimeError("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env var")

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        parts = _chunks(text)
        plain_fallback = False
        for part in parts:
            response = requests.post(
                url, json={"chat_id": chat_id, "text": part, "parse_mode": "Markdown"}, timeout=TIMEOUT,
            )
            if response.status_code == 400:
                # Markdown của model hay lệch (dấu _ * [ lẻ) → Telegram báo "can't parse entities".
                # Gửi lại dạng văn bản thường thay vì báo lỗi cho người dùng.
                response = requests.post(url, json={"chat_id": chat_id, "text": part}, timeout=TIMEOUT)
                plain_fallback = True
            response.raise_for_status()
        return {"tool": "send_telegram", "status": "sent", "messages": len(parts), "plain_text_fallback": plain_fallback}
    except Exception as exc:
        return err("send_telegram", exc)