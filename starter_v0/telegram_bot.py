from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

import chat  # load .env + dùng lại run_model_tool_loop, trim_history, write_transcript
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version

API = "https://api.telegram.org/bot{token}/{method}"
MAX_MSG = 4000  # Telegram giới hạn 4096 ký tự / tin


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


class TelegramAPI:
    def __init__(self, token: str) -> None:
        self.token = token

    def call(self, method: str, timeout: float = 30, **params: Any) -> dict[str, Any]:
        resp = requests.post(API.format(token=self.token, method=method), json=params, timeout=timeout)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} lỗi: {data.get('description')}")
        return data

    def send_text(self, chat_id: int, text: str) -> None:
        text = text or "(không có nội dung)"
        for i in range(0, len(text), MAX_MSG):
            # Gửi plain text (không parse_mode) để không lỗi khi model trả markdown lệch.
            self.call("sendMessage", chat_id=chat_id, text=text[i:i + MAX_MSG])


class Session:
    """State của một cuộc chat Telegram: history + transcript."""

    def __init__(self, chat_id: int, cfg: argparse.Namespace, model: str | None) -> None:
        self.chat_id = chat_id
        self.history: list[dict[str, str]] = []
        self.turn_index = 0
        av = build_artifact_version(cfg.version, cfg.system_prompt, cfg.tools)
        tid = "_".join([
            chat.safe_slug(cfg.version),
            chat.safe_slug(cfg.provider),
            f"telegram{chat_id}",
            datetime.now().strftime("%Y%m%dT%H%M%S%f"),
        ])
        self.path = cfg.transcripts_dir / f"{tid}.transcript.json"
        self.transcript: dict[str, Any] = {
            "transcript_id": tid,
            **artifact_version_dict(av),
            "provider": cfg.provider,
            "model": model,
            "channel": "telegram",
            "telegram_chat_id": chat_id,
            "system_prompt": str(cfg.system_prompt),
            "tools": str(cfg.tools),
            "history_window": cfg.history_window,
            "max_tool_rounds": cfg.max_tool_rounds,
            "created_at": chat.now_iso(),
            "updated_at": chat.now_iso(),
            "turns": [],
        }


def format_reply(result: dict[str, Any]) -> str:
    tools_used = [ev.get("tool") for ev in result.get("tool_events", [])]
    answer = result.get("assistant_text") or ""
    if tools_used:
        return f"🔧 {', '.join(tools_used)}\n\n{answer}"
    return answer


def main() -> None:
    ap = argparse.ArgumentParser(description="Telegram bot cho Research Agent")
    ap.add_argument("--provider", choices=["openrouter", "openai", "anthropic", "gemini", "ollama"], default="openrouter")
    ap.add_argument("--model", default=None)
    ap.add_argument("--version", required=True)
    ap.add_argument("--system-prompt", type=Path, default=chat.ARTIFACTS_DIR / "system_prompt.md")
    ap.add_argument("--tools", type=Path, default=chat.ARTIFACTS_DIR / "tools.yaml")
    ap.add_argument("--transcripts-dir", type=Path, default=chat.ROOT / "transcripts")
    ap.add_argument("--history-window", type=int, default=5)
    ap.add_argument("--max-tool-rounds", type=int, default=4)
    cfg = ap.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Thiếu TELEGRAM_BOT_TOKEN trong .env")
    allowed = {s.strip() for s in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if s.strip()}

    system_prompt = cfg.system_prompt.read_text(encoding="utf-8")
    openai_tools = to_openai_tools(load_tool_declarations(cfg.tools))
    provider = make_provider(cfg.provider)
    model = cfg.model or getattr(provider, "default_model", None)
    av = build_artifact_version(cfg.version, cfg.system_prompt, cfg.tools)

    tg = TelegramAPI(token)
    me = tg.call("getMe")["result"]
    tg.call("deleteWebhook")  # long polling không chạy được nếu bot đang có webhook
    log(f"Bot @{me.get('username')} đang chạy | {av.artifact_version} | provider={cfg.provider} model={model}")
    if not allowed:
        log("CẢNH BÁO: chưa đặt TELEGRAM_ALLOWED_CHAT_IDS → ai nhắn bot cũng dùng được (tốn credit của bạn).")

    sessions: dict[int, Session] = {}
    offset = 0
    while True:
        try:
            # Long polling: Telegram giữ kết nối tối đa 30s chờ tin mới.
            updates = requests.post(
                API.format(token=token, method="getUpdates"),
                json={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                timeout=40,
            ).json()
            if not updates.get("ok"):
                log(f"getUpdates lỗi: {updates.get('description')}")
                time.sleep(5)
                continue
        except requests.RequestException as exc:
            log(f"Mất kết nối Telegram: {exc}. Thử lại sau 5s.")
            time.sleep(5)
            continue

        for upd in updates.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat_id = (msg.get("chat") or {}).get("id")
            if not text or chat_id is None:
                continue

            if text.startswith("/id"):
                tg.send_text(chat_id, f"Chat id của bạn: {chat_id}")
                continue
            if allowed and str(chat_id) not in allowed:
                tg.send_text(chat_id, "Bot này chỉ dành cho nhóm phát triển. Gửi /id để lấy chat id nhờ admin thêm vào.")
                log(f"Chặn chat {chat_id} (không nằm trong TELEGRAM_ALLOWED_CHAT_IDS)")
                continue
            if text.startswith("/start"):
                tg.send_text(chat_id, "Xin chào! Mình là Research Agent: tìm tin AI/tech trên web, Twitter, Hacker News, "
                                      "đọc link, tìm paper.\nVD: 'Tin AI hôm nay có gì nổi bật?'\n/reset để bắt đầu lại.")
                continue
            if text.startswith("/reset"):
                sessions.pop(chat_id, None)
                tg.send_text(chat_id, "Đã bắt đầu hội thoại mới.")
                continue
            if text.startswith("/version"):
                tg.send_text(chat_id, f"{av.artifact_version}\nprovider={cfg.provider} model={model}")
                continue

            sess = sessions.get(chat_id)
            if sess is None:
                sess = sessions[chat_id] = Session(chat_id, cfg, model)
            sess.turn_index += 1
            log(f"chat {chat_id} > {text[:80]}")

            try:
                tg.call("sendChatAction", chat_id=chat_id, action="typing")
            except Exception:
                pass

            messages = [
                {"role": "system", "content": system_prompt},
                *chat.trim_history(sess.history, cfg.history_window),
                {"role": "user", "content": text},
            ]
            turn: dict[str, Any] = {
                "turn_index": sess.turn_index,
                "started_at": chat.now_iso(),
                "user": text,
                "status": "started",
                "assistant_text": None,
                "rounds": [],
                "tool_events": [],
            }
            try:
                result = chat.run_model_tool_loop(
                    provider=provider, messages=messages, tools=openai_tools,
                    model=cfg.model, max_tool_rounds=cfg.max_tool_rounds,
                )
                turn.update(result)
                answer = result["assistant_text"]
                sess.history += [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
                reply = format_reply(result)
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                turn.update({"status": "provider_error", "error": err})
                reply = f"⚠️ Lỗi: {err}"

            turn["ended_at"] = chat.now_iso()
            sess.transcript["turns"].append(turn)
            chat.write_transcript(sess.path, sess.transcript)
            try:
                tg.send_text(chat_id, reply)
            except Exception as exc:
                log(f"Không gửi được trả lời cho {chat_id}: {exc}")
            log(f"chat {chat_id} < {turn['status']} ({len(turn.get('tool_events', []))} tool call)")


if __name__ == "__main__":
    main()