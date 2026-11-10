"""UI chat tối thiểu bằng Streamlit, tái sử dụng vòng lặp tool trong chat.py.

Đặt cạnh chat.py (cùng thư mục có env_loader.py, providers/, tools.py, artifacts/).
Chạy: streamlit run app.py
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

import chat  # chat.py hiện có: dùng lại run_model_tool_loop, trim_history, write_transcript...
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version

PROVIDERS = ["openrouter", "openai", "anthropic", "gemini", "ollama"]
SYSTEM_PROMPT_PATH: Path = chat.ARTIFACTS_DIR / "system_prompt.md"
TOOLS_PATH: Path = chat.ARTIFACTS_DIR / "tools.yaml"
TRANSCRIPTS_DIR: Path = chat.ROOT / "transcripts"


# ---------- artifact chung (prompt + tool declarations) ----------
@st.cache_resource
def load_artifacts():
    prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    tools = to_openai_tools(load_tool_declarations(TOOLS_PATH))
    return prompt, tools


@st.cache_resource
def get_provider(name: str):
    return make_provider(name)


# ---------- state ----------
def new_conversation() -> None:
    st.session_state.messages = []      # để hiển thị: {"role","content","tool_events","status"}
    st.session_state.history = []       # để gửi cho model: {"role","content"}
    st.session_state.transcript = None  # tạo ở lượt đầu tiên
    st.session_state.transcript_path = None
    st.session_state.turn_index = 0


def start_transcript(provider_name: str, model: str | None, version: str, window: int, rounds: int):
    provider = get_provider(provider_name)
    av = build_artifact_version(version, SYSTEM_PROMPT_PATH, TOOLS_PATH)
    tid = "_".join([
        chat.safe_slug(version),
        chat.safe_slug(provider_name),
        datetime.now().strftime("%Y%m%dT%H%M%S%f"),
    ])
    st.session_state.transcript_path = TRANSCRIPTS_DIR / f"{tid}.transcript.json"
    st.session_state.transcript = {
        "transcript_id": tid,
        **artifact_version_dict(av),
        "provider": provider_name,
        "model": model or getattr(provider, "default_model", None),
        "system_prompt": str(SYSTEM_PROMPT_PATH),
        "tools": str(TOOLS_PATH),
        "history_window": window,
        "max_tool_rounds": rounds,
        "created_at": chat.now_iso(),
        "updated_at": chat.now_iso(),
        "turns": [],
    }


def render_message(msg: dict[str, Any]) -> None:
    with st.chat_message(msg["role"]):
        for ev in msg.get("tool_events", []):
            with st.expander(f"🔧 {ev.get('tool')}"):
                st.json({"args": ev.get("args"), "result": ev.get("result")})
        st.markdown(msg["content"])
        if msg.get("status") == "waiting_for_user":
            st.caption("⏸ Agent cần bạn bổ sung thông tin.")


# ---------- UI ----------
st.set_page_config(page_title="Research Agent", page_icon="💬")
st.title("💬 Research Agent")

if "messages" not in st.session_state:
    new_conversation()

locked = bool(st.session_state.messages)  # khoá cấu hình sau khi đã chat
with st.sidebar:
    provider_name = st.selectbox("Provider", PROVIDERS, disabled=locked)
    model = st.text_input("Model (để trống = mặc định)", disabled=locked) or None
    version = st.text_input("Artifact version", value="v0", disabled=locked)
    window = st.number_input("History window (cặp user/assistant)", 0, 20, 5, disabled=locked)
    max_rounds = st.number_input("Max tool rounds", 1, 10, 4, disabled=locked)
    st.button("➕ Cuộc hội thoại mới", on_click=new_conversation, use_container_width=True)
    if st.button("🔄 Reload prompt/tools", use_container_width=True):
        load_artifacts.clear()
        st.rerun()
    if st.session_state.transcript_path:
        st.caption(f"Transcript: `{st.session_state.transcript_path.name}`")

try:
    system_prompt, openai_tools = load_artifacts()
    provider = get_provider(provider_name)
except Exception as exc:
    st.error(f"Không khởi tạo được artifact/provider: {type(exc).__name__}: {exc}")
    st.stop()

for m in st.session_state.messages:
    render_message(m)

if user_text := st.chat_input("Nhập yêu cầu..."):
    user_msg = {"role": "user", "content": user_text}
    st.session_state.messages.append(user_msg)
    render_message(user_msg)

    if st.session_state.transcript is None:
        start_transcript(provider_name, model, version, int(window), int(max_rounds))
    st.session_state.turn_index += 1

    messages = [
        {"role": "system", "content": system_prompt},
        *chat.trim_history(st.session_state.history, int(window)),
        {"role": "user", "content": user_text},
    ]
    turn: dict[str, Any] = {
        "turn_index": st.session_state.turn_index,
        "started_at": chat.now_iso(),
        "user": user_text,
        "status": "started",
        "assistant_text": None,
        "rounds": [],
        "tool_events": [],
    }

    with st.chat_message("assistant"):
        with st.spinner("Đang xử lý..."):
            try:
                result = chat.run_model_tool_loop(
                    provider=provider,
                    messages=messages,
                    tools=openai_tools,
                    model=model,
                    max_tool_rounds=int(max_rounds),
                )
                turn.update(result)
                answer = result["assistant_text"]
                st.session_state.history += [
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": answer},
                ]
                assistant_msg = {
                    "role": "assistant",
                    "content": answer,
                    "tool_events": result["tool_events"],
                    "status": result["status"],
                }
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                turn.update({"status": "provider_error", "error": err})
                assistant_msg = {"role": "assistant", "content": f"⚠️ {err}", "status": "provider_error"}
        render_message(assistant_msg)

    st.session_state.messages.append(assistant_msg)
    turn["ended_at"] = chat.now_iso()
    st.session_state.transcript["turns"].append(turn)
    chat.write_transcript(st.session_state.transcript_path, st.session_state.transcript)
    st.rerun()  # cập nhật sidebar (khoá cấu hình, tên transcript)
