from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

import chat  # load .env + dùng lại run_model_tool_loop, trim_history, write_transcript...
from providers import make_provider
from tools import TOOL_FUNCTIONS, load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version, file_hash, short_hash

# Streamlit mới bỏ use_container_width, dùng width="stretch"; bản cũ chỉ có use_container_width.
_ST_VER = tuple(int(x) for x in re.findall(r"\d+", st.__version__)[:2])
STRETCH: dict[str, Any] = {"width": "stretch"} if _ST_VER >= (1, 46) else {"use_container_width": True}

PROVIDERS = ["openrouter", "openai", "anthropic", "gemini", "ollama"]
ROOT: Path = chat.ROOT
ARTIFACTS_DIR: Path = chat.ARTIFACTS_DIR
VERSIONS_DIR: Path = ARTIFACTS_DIR / "versions"
RUNS_DIR: Path = ROOT / "runs"
TRANSCRIPTS_DIR: Path = ROOT / "transcripts"
VERSION_LOG: Path = ARTIFACTS_DIR / "version_log.csv"
BOT_LOG: Path = ROOT / "transcripts" / "telegram_bot.log"
CURRENT = "current (artifacts/)"
METRICS = ["case_accuracy", "tool_routing_accuracy", "argument_accuracy", "multiturn_accuracy"]
RUN_NAME = re.compile(r"^(?P<version>[^_]+)_(?P<phase>[^_]+)_(?P<suite>[^_]+)_(?P<provider>[^_]+)_(?P<ts>[^_.]+)\.json$")


# ======================================================================
# Version helpers
# ======================================================================
def natural_key(text: str) -> list[Any]:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


def list_versions() -> list[str]:
    if not VERSIONS_DIR.exists():
        return []
    names = [
        d.name for d in VERSIONS_DIR.iterdir()
        if d.is_dir() and (d / "system_prompt.md").exists() and (d / "tools.yaml").exists()
    ]
    return sorted(names, key=natural_key)


def version_paths(choice: str) -> tuple[Path, Path]:
    if choice == CURRENT:
        return ARTIFACTS_DIR / "system_prompt.md", ARTIFACTS_DIR / "tools.yaml"
    return VERSIONS_DIR / choice / "system_prompt.md", VERSIONS_DIR / choice / "tools.yaml"


def current_snapshot() -> str | None:
    """Snapshot nào giống hệt file đang dùng trong artifacts/ (so hash) → coi đó là version hiện tại."""
    try:
        cur = tuple(file_hash(p) for p in version_paths(CURRENT))
    except OSError:
        return None
    for v in reversed(list_versions()):
        if tuple(file_hash(p) for p in version_paths(v)) == cur:
            return v
    return None


def version_options() -> list[str]:
    """Danh sách version để chọn. Nếu artifacts/ trùng một snapshot thì không hiện thêm mục 'current'."""
    versions = list_versions()
    return versions if current_snapshot() else versions + [CURRENT]


def version_label(v: str) -> str:
    if v == CURRENT:
        return "hiện tại (artifacts/, chưa lưu snapshot)"
    return f"{v} (hiện tại)" if v == current_snapshot() else v


def default_version_index(options: list[str]) -> int:
    cur = current_snapshot() or CURRENT
    return options.index(cur) if cur in options else len(options) - 1


def save_snapshot(label: str) -> Path:
    dest = VERSIONS_DIR / label
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("system_prompt.md", "tools.yaml"):
        shutil.copy2(ARTIFACTS_DIR / name, dest / name)  # giữ nguyên byte → hash không đổi
    return dest


@st.cache_resource
def load_artifacts(prompt_path: str, tools_path: str, stamp: float):
    """stamp = mtime: file đổi thì cache tự làm mới (tham số không có _ nên được đưa vào cache key)."""
    prompt = Path(prompt_path).read_text(encoding="utf-8")
    tools = to_openai_tools(load_tool_declarations(Path(tools_path)))
    return prompt, tools


@st.cache_resource
def get_provider(name: str):
    return make_provider(name)


# ======================================================================
# Run JSON helpers (cho trang So sánh)
# ======================================================================
def _get(obj: Any, *keys: str) -> Any:
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            return obj[k]
    return None


def case_results(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """case_id -> {passed, failures}. Chịu được vài kiểu cấu trúc results khác nhau."""
    out: dict[str, dict[str, Any]] = {}
    for r in data.get("results", []) or []:
        if not isinstance(r, dict):
            continue
        case = r.get("case") if isinstance(r.get("case"), dict) else {}
        cid = _get(r, "case_id", "id") or _get(case, "id")
        res = r.get("result") if isinstance(r.get("result"), dict) else r
        if not cid:
            continue
        out[str(cid)] = {"passed": _get(res, "passed"), "failures": _get(res, "failures")}
    return out


@st.cache_data(show_spinner=False)
def load_runs(stamp: float) -> list[dict[str, Any]]:
    runs = []
    if not RUNS_DIR.exists():
        return runs
    for path in RUNS_DIR.glob("*.json"):
        m = RUN_NAME.match(path.name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary = data.get("summary") or {}
        runs.append({
            "file": path.name,
            "version": m.group("version") if m else str(data.get("version", "?")),
            "suite": m.group("suite") if m else str(data.get("suite", "?")),
            "provider": m.group("provider") if m else str(data.get("provider", "?")),
            "mtime": path.stat().st_mtime,
            "artifact_version": data.get("artifact_version", ""),
            "prompt_hash": str(data.get("prompt_hash", "")),
            "tools_hash": str(data.get("tools_hash", "")),
            "passed": summary.get("passed_cases"),
            "total": summary.get("measured_cases", summary.get("total_cases")),
            **{k: summary.get(k) for k in METRICS},
            "cases": case_results(data),
        })
    return runs


def dir_stamp(path: Path) -> float:
    if not path.exists():
        return 0.0
    return max([path.stat().st_mtime] + [p.stat().st_mtime for p in path.glob("*")])


# ======================================================================
# Telegram helpers
# ======================================================================
def mask(value: str | None) -> str:
    if not value:
        return "❌ chưa đặt"
    return f"✅ {value[:4]}…{value[-3:]}" if len(value) > 10 else "✅ đã đặt"


def send_to_telegram(text: str) -> dict[str, Any]:
    """Gọi đúng tool `send` của agent với confirmed=True (người dùng đã tick xác nhận trên UI)."""
    return TOOL_FUNCTIONS["send"](text=text, confirmed=True)


@st.cache_resource
def bot_holder() -> dict[str, Any]:
    """Giữ tiến trình bot qua các lần Streamlit rerun (dùng chung mọi session)."""
    return {"proc": None, "cmd": None, "started_at": None}


def bot_running() -> bool:
    proc = bot_holder()["proc"]
    return proc is not None and proc.poll() is None


def start_bot(provider: str, version_choice: str, label: str) -> None:
    prompt_path, tools_path = version_paths(version_choice)
    BOT_LOG.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-u", str(ROOT / "telegram_bot.py"),
        "--provider", provider, "--version", label,
        "--system-prompt", str(prompt_path), "--tools", str(tools_path),
    ]
    log_file = open(BOT_LOG, "a", encoding="utf-8")  # noqa: SIM115 — đóng khi tiến trình kết thúc
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    bot_holder().update(proc=proc, cmd=" ".join(cmd[2:]), started_at=datetime.now().strftime("%H:%M:%S"))


def stop_bot() -> None:
    proc = bot_holder()["proc"]
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    bot_holder().update(proc=None)


def tail(path: Path, n: int = 30) -> str:
    if not path.exists():
        return "(chưa có log)"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])


# ======================================================================
# Chat state
# ======================================================================
def new_conversation() -> None:
    st.session_state.messages = []      # hiển thị: {"role","content","tool_events","status"}
    st.session_state.history = []       # gửi cho model: {"role","content"}
    st.session_state.transcript = None
    st.session_state.transcript_path = None
    st.session_state.turn_index = 0


def start_transcript(provider_name, model, label, prompt_path, tools_path, window, rounds) -> None:
    provider = get_provider(provider_name)
    av = build_artifact_version(label, prompt_path, tools_path)
    tid = "_".join([chat.safe_slug(label), chat.safe_slug(provider_name), datetime.now().strftime("%Y%m%dT%H%M%S%f")])
    st.session_state.transcript_path = TRANSCRIPTS_DIR / f"{tid}.transcript.json"
    st.session_state.transcript = {
        "transcript_id": tid,
        **artifact_version_dict(av),
        "provider": provider_name,
        "model": model or getattr(provider, "default_model", None),
        "channel": "streamlit",
        "system_prompt": str(prompt_path),
        "tools": str(tools_path),
        "history_window": window,
        "max_tool_rounds": rounds,
        "created_at": chat.now_iso(),
        "updated_at": chat.now_iso(),
        "turns": [],
        "ui_actions": [],  # VD gửi Telegram từ nút trên UI
    }


def render_message(msg: dict[str, Any]) -> None:
    with st.chat_message(msg["role"]):
        for ev in msg.get("tool_events", []):
            with st.expander(f"🔧 {ev.get('tool')}"):
                st.json({"args": ev.get("args"), "result": ev.get("result")})
        st.markdown(msg["content"])
        if msg.get("status") == "waiting_for_user":
            st.caption("⏸ Agent cần bạn bổ sung thông tin.")


# ======================================================================
# Pages
# ======================================================================
def page_chat(cfg: dict[str, Any]) -> None:
    st.title("💬 Research Agent")
    st.caption(f"Version **{cfg['label']}** · `{cfg['artifact_version']}` · provider `{cfg['provider']}`")

    try:
        system_prompt, openai_tools = load_artifacts(
            str(cfg["prompt_path"]), str(cfg["tools_path"]),
            max(cfg["prompt_path"].stat().st_mtime, cfg["tools_path"].stat().st_mtime),
        )
        provider = get_provider(cfg["provider"])
    except Exception as exc:
        st.error(f"Không khởi tạo được artifact/provider: {type(exc).__name__}: {exc}")
        st.stop()

    for m in st.session_state.messages:
        render_message(m)

    # ---- Gửi câu trả lời gần nhất lên Telegram (có xác nhận) ----
    last_answer = next((m for m in reversed(st.session_state.messages)
                        if m["role"] == "assistant" and m.get("status") == "answered"), None)
    if last_answer:
        with st.expander("📤 Gửi câu trả lời này lên kênh Telegram"):
            text = st.text_area("Nội dung sẽ gửi (sửa được)", value=last_answer["content"], height=200, key="tg_chat_text")
            ok = st.checkbox("Tôi đã đọc lại và xác nhận gửi nội dung này lên kênh Telegram", key="tg_chat_confirm")
            if st.button("Gửi", disabled=not ok, key="tg_chat_send"):
                res = send_to_telegram(text)
                if st.session_state.transcript is not None:
                    st.session_state.transcript["ui_actions"].append({
                        "at": chat.now_iso(), "action": "send", "confirmed_by_user": True,
                        "args": {"text": text, "confirmed": True}, "result": res,
                    })
                    chat.write_transcript(st.session_state.transcript_path, st.session_state.transcript)
                (st.success if res.get("status") == "sent" else st.error)(json.dumps(res, ensure_ascii=False))

    if user_text := st.chat_input("Nhập yêu cầu..."):
        user_msg = {"role": "user", "content": user_text}
        st.session_state.messages.append(user_msg)
        render_message(user_msg)

        if st.session_state.transcript is None:
            start_transcript(cfg["provider"], cfg["model"], cfg["label"], cfg["prompt_path"],
                             cfg["tools_path"], cfg["window"], cfg["max_rounds"])
        st.session_state.turn_index += 1

        messages = [
            {"role": "system", "content": system_prompt},
            *chat.trim_history(st.session_state.history, cfg["window"]),
            {"role": "user", "content": user_text},
        ]
        turn: dict[str, Any] = {
            "turn_index": st.session_state.turn_index, "started_at": chat.now_iso(), "user": user_text,
            "status": "started", "assistant_text": None, "rounds": [], "tool_events": [],
        }

        with st.chat_message("assistant"):
            with st.spinner("Đang xử lý..."):
                try:
                    result = chat.run_model_tool_loop(
                        provider=provider, messages=messages, tools=openai_tools,
                        model=cfg["model"], max_tool_rounds=cfg["max_rounds"],
                    )
                    turn.update(result)
                    answer = result["assistant_text"]
                    st.session_state.history += [
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": answer},
                    ]
                    assistant_msg = {"role": "assistant", "content": answer,
                                     "tool_events": result["tool_events"], "status": result["status"]}
                except Exception as exc:
                    err = f"{type(exc).__name__}: {exc}"
                    turn.update({"status": "provider_error", "error": err})
                    assistant_msg = {"role": "assistant", "content": f"⚠️ {err}", "status": "provider_error"}

        st.session_state.messages.append(assistant_msg)
        turn["ended_at"] = chat.now_iso()
        st.session_state.transcript["turns"].append(turn)
        chat.write_transcript(st.session_state.transcript_path, st.session_state.transcript)
        st.rerun()


def page_compare() -> None:
    st.title("📊 So sánh version")
    runs = load_runs(dir_stamp(RUNS_DIR))
    if not runs:
        st.info("Chưa có run nào trong `runs/`. Chạy `run_eval.py` trước.")
        return

    c1, c2 = st.columns(2)
    suites = sorted({r["suite"] for r in runs})
    suite = c1.selectbox("Suite", suites, index=suites.index("base") if "base" in suites else 0)
    latest_only = c2.checkbox("Chỉ lấy run mới nhất của mỗi version", value=True)

    selected = [r for r in runs if r["suite"] == suite]
    if latest_only:
        best: dict[str, dict[str, Any]] = {}
        for r in selected:
            if r["version"] not in best or r["mtime"] > best[r["version"]]["mtime"]:
                best[r["version"]] = r
        selected = list(best.values())
    selected.sort(key=lambda r: (natural_key(r["version"]), r["mtime"]))
    col_name = (lambda r: r["version"]) if latest_only else (lambda r: f"{r['version']} ({r['file'][-21:-5]})")

    # ---- 1. Metric ----
    st.subheader("1. Metric theo version")
    df = pd.DataFrame([{
        "version": col_name(r), "pass": f"{r['passed']}/{r['total']}", **{k: r[k] for k in METRICS},
        "artifact_version": r["artifact_version"], "file": r["file"],
    } for r in selected])
    st.dataframe(df, **STRETCH, hide_index=True)
    chart_df = df.set_index("version")[METRICS].apply(pd.to_numeric, errors="coerce")
    st.line_chart(chart_df)

    # ---- 2. PASS/FAIL từng case ----
    st.subheader("2. PASS / FAIL từng case")
    case_ids = sorted({cid for r in selected for cid in r["cases"]}, key=natural_key)
    if case_ids:
        mark = {True: "✅", False: "❌", None: "—"}
        matrix = pd.DataFrame(
            {col_name(r): [mark.get(r["cases"].get(cid, {}).get("passed")) for cid in case_ids] for r in selected},
            index=case_ids,
        )
        only_changed = st.checkbox("Chỉ hiện case có thay đổi giữa các version", value=False)
        if only_changed:
            matrix = matrix[matrix.nunique(axis=1) > 1]
        st.dataframe(matrix, **STRETCH)

        with st.expander("Chi tiết lỗi (failures) của các case FAIL"):
            rows = [{"version": col_name(r), "case": cid, "failures": str(info.get("failures"))}
                    for r in selected for cid, info in r["cases"].items() if info.get("passed") is False]
            st.dataframe(pd.DataFrame(rows), **STRETCH, hide_index=True) if rows else st.write("Không có case FAIL.")
    else:
        st.caption("Không đọc được kết quả từng case trong run JSON.")

    # ---- 3. version_log.csv ----
    st.subheader("3. artifacts/version_log.csv")
    if VERSION_LOG.exists():
        st.dataframe(pd.read_csv(VERSION_LOG), **STRETCH, hide_index=True)
    else:
        st.caption("Chưa có version_log.csv — chạy `python scripts/make_version_log.py`.")

    # ---- 4. Snapshot có khớp run không ----
    versions = list_versions()
    st.subheader("4. Snapshot có khớp bản đã chạy eval không?")
    if versions:
        check = []
        for v in versions:
            p, t = version_paths(v)
            ph, th = file_hash(p), file_hash(t)
            vr = [r for r in runs if r["version"] == v]
            match_p = any(r["prompt_hash"].startswith(ph[:12]) or ph.startswith(r["prompt_hash"][:12] or "#") for r in vr)
            match_t = any(r["tools_hash"].startswith(th[:12]) or th.startswith(r["tools_hash"][:12] or "#") for r in vr)
            check.append({"version": v, "prompt_hash": short_hash(ph), "tools_hash": short_hash(th),
                          "prompt khớp run": "✅" if match_p else ("—" if not vr else "⚠️"),
                          "tools khớp run": "✅" if match_t else ("—" if not vr else "⚠️")})
        st.dataframe(pd.DataFrame(check), **STRETCH, hide_index=True)
        st.caption("⚠️ = nội dung snapshot khác bản đã chạy eval (VD dựng lại sau). — = chưa có run cho version này.")

    # ---- 5. Diff prompt/tools ----
    st.subheader("5. So sánh prompt / tools giữa 2 version")
    options = version_options()
    if len(options) < 2:
        st.caption("Cần ít nhất 2 version trong `artifacts/versions/` để so sánh.")
        return
    d1, d2 = st.columns(2)
    a = d1.selectbox("Từ version", options, index=max(len(options) - 2, 0), format_func=version_label)
    b = d2.selectbox("Đến version", options, index=len(options) - 1, format_func=version_label)
    for idx, fname in enumerate(("system_prompt.md", "tools.yaml")):
        pa, pb = version_paths(a)[idx], version_paths(b)[idx]
        diff = list(difflib.unified_diff(
            pa.read_text(encoding="utf-8").splitlines(), pb.read_text(encoding="utf-8").splitlines(),
            fromfile=f"{a}/{fname}", tofile=f"{b}/{fname}", lineterm="",
        ))
        with st.expander(f"{fname}: {sum(1 for l in diff if l.startswith(('+', '-')) and not l.startswith(('+++', '---')))} dòng thay đổi",
                         expanded=idx == 0):
            st.code("\n".join(diff) or "(giống nhau)", language="diff")


# ======================================================================
# 🆚 So sánh câu trả lời giữa các version
# ======================================================================
DATA_DIR: Path = ROOT / "data"
ANALYSIS_DIR: Path = ROOT / "analysis"


@st.cache_data(show_spinner=False)
def load_eval_cases(stamp: float) -> list[dict[str, Any]]:
    cases = []
    for path in sorted(DATA_DIR.glob("eval_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for c in data.get("cases", []):
            turns = [t["content"] for t in c.get("turns", []) if t.get("role") == "user"] or [c.get("query", "")]
            cases.append({
                "label": f"[{path.stem.replace('eval_', '')}] {c.get('id')}",
                "turns": [t for t in turns if t],
                "expect": c.get("expect"),
                "what": (c.get("metadata") or {}).get("what_it_tests", ""),
            })
    return cases


def _dry_send(text: str = "", confirmed: bool = False, **_: Any) -> dict[str, Any]:
    """Thay cho tool send khi so sánh: KHÔNG gửi thật, chỉ ghi lại model định gửi gì."""
    return {"tool": "send_telegram", "status": "dry_run_not_sent", "confirmed": confirmed, "text": text}


def run_one_version(version: str, turns: list[str], provider_name: str, model: str | None,
                    execute_tools: bool, max_rounds: int) -> dict[str, Any]:
    prompt_path, tools_path = version_paths(version)
    av = build_artifact_version(version if version != CURRENT else "current", prompt_path, tools_path)
    prompt = prompt_path.read_text(encoding="utf-8")
    tools = to_openai_tools(load_tool_declarations(tools_path))
    provider = get_provider(provider_name)
    # Các lượt trước là user message nối tiếp, giống cách eval chấm case multi-turn.
    messages = [{"role": "system", "content": prompt}, *[{"role": "user", "content": t} for t in turns]]
    started = time.perf_counter()
    try:
        if execute_tools:
            res = chat.run_model_tool_loop(provider=provider, messages=messages, tools=tools,
                                           model=model, max_tool_rounds=max_rounds)
            calls = [c for r in res["rounds"] for c in r["tool_calls"]]
            out = {"status": res["status"], "text": res["assistant_text"], "tool_calls": calls,
                   "tool_events": res["tool_events"]}
        else:
            resp = provider.complete(messages, tools, model=model, temperature=0.0)
            out = {"status": "first_response_only", "text": resp.text or "",
                   "tool_calls": [{"name": c.name, "args": c.args} for c in resp.tool_calls], "tool_events": []}
    except Exception as exc:
        out = {"status": "provider_error", "text": f"{type(exc).__name__}: {exc}", "tool_calls": [], "tool_events": []}
    out.update(version=version, artifact_version=av.artifact_version, seconds=round(time.perf_counter() - started, 1))
    return out


def match_expect(expect: dict[str, Any] | None, calls: list[dict[str, Any]]) -> str:
    """Chấm nhanh kiểu eval (tên tool + args là tập con). Chỉ để tham khảo, số chính thức lấy từ run_eval.py."""
    if not expect:
        return ""
    if expect.get("no_tool"):
        return "✅ khớp kỳ vọng" if not calls else "❌ lẽ ra không gọi tool"
    expected = expect.get("tool_calls", [])
    remaining = list(calls)
    for exp in expected:
        hit = next((c for c in remaining if c.get("name") == exp.get("name") and all(
            str((c.get("args") or {}).get(k)).lower() == str(v).lower() for k, v in (exp.get("args") or {}).items())), None)
        if hit is None:
            return f"❌ thiếu/sai {exp.get('name')}({json.dumps(exp.get('args'), ensure_ascii=False)})"
        remaining.remove(hit)
    return "✅ khớp kỳ vọng" if not remaining else f"⚠️ gọi thừa {[c.get('name') for c in remaining]}"


def page_answers(cfg: dict[str, Any]) -> None:
    st.title("🆚 So sánh câu trả lời giữa các version")
    st.caption("Cùng một câu hỏi, chạy song song trên nhiều version để thấy prompt/tools thay đổi hành vi agent ra sao.")

    versions = version_options()
    chosen = st.multiselect("Version cần so sánh", versions, format_func=version_label,
                            default=[v for v in versions if v != CURRENT][-4:] or versions)

    cases = load_eval_cases(dir_stamp(DATA_DIR))
    source = st.radio("Câu hỏi", ["Tự nhập", "Lấy từ eval case"], horizontal=True)
    expect = None
    if source == "Lấy từ eval case" and cases:
        case = cases[st.selectbox("Eval case", range(len(cases)), format_func=lambda i: cases[i]["label"])]
        turns, expect = case["turns"], case["expect"]
        st.caption(f"Kiểm tra: {case['what']}")
        for i, t in enumerate(turns, 1):
            st.markdown(f"**Lượt {i}:** {t}")
        st.caption(f"Kỳ vọng: `{json.dumps(expect, ensure_ascii=False)}`")
    else:
        raw = st.text_area("Câu hỏi (nhiều lượt: mỗi dòng là một lượt của user)", height=100,
                           placeholder="Đăng bản tin này lên Telegram giúp mình")
        turns = [line.strip() for line in raw.splitlines() if line.strip()]

    c1, c2 = st.columns(2)
    execute = c1.toggle("Chạy tool thật và để agent trả lời đầy đủ", value=False,
                        help="Tắt: chỉ xem model CHỌN tool gì ở bước đầu (nhanh, rẻ, giống cách eval chấm). "
                             "Bật: chạy cả vòng tool → câu trả lời cuối. Tool send luôn ở chế độ giả, không gửi thật.")
    c2.caption(f"Provider: **{cfg['provider']}** · model: **{cfg['model'] or 'mặc định'}** (đổi ở sidebar)")

    if st.button("▶️ So sánh", type="primary", disabled=not (chosen and turns)):
        original_send = TOOL_FUNCTIONS.get("send")
        TOOL_FUNCTIONS["send"] = _dry_send  # chặn gửi thật trong lúc so sánh
        try:
            with st.spinner(f"Đang chạy {len(chosen)} version..."):
                with ThreadPoolExecutor(max_workers=min(4, len(chosen))) as pool:
                    results = list(pool.map(lambda v: run_one_version(
                        v, turns, cfg["provider"], cfg["model"], execute, cfg["max_rounds"]), chosen))
        finally:
            if original_send is not None:
                TOOL_FUNCTIONS["send"] = original_send
        for r in results:
            r["verdict"] = match_expect(expect, r["tool_calls"])
        st.session_state.answer_cmp = {"turns": turns, "expect": expect, "execute": execute,
                                       "provider": cfg["provider"], "model": cfg["model"],
                                       "at": chat.now_iso(), "results": results}

    cmp_ = st.session_state.get("answer_cmp")
    if not cmp_:
        return

    st.divider()
    st.markdown("**Tóm tắt**")
    st.dataframe(pd.DataFrame([{
        "version": r["version"],
        "tool calls": ", ".join(f"{c['name']}({json.dumps(c.get('args'), ensure_ascii=False)})" for c in r["tool_calls"]) or "— (không gọi tool)",
        "đánh giá": r["verdict"], "status": r["status"], "giây": r["seconds"],
    } for r in cmp_["results"]]), hide_index=True, **STRETCH)

    cols = st.columns(len(cmp_["results"]))
    for col, r in zip(cols, cmp_["results"]):
        with col:
            st.subheader(version_label(r["version"]))
            st.caption(f"`{r['artifact_version']}` · {r['seconds']}s")
            if r["verdict"]:
                st.markdown(r["verdict"])
            st.markdown("**Tool calls**")
            if r["tool_calls"]:
                for c in r["tool_calls"]:
                    st.code(f"{c['name']}({json.dumps(c.get('args'), ensure_ascii=False, indent=1)})", language="python")
            else:
                st.caption("Không gọi tool")
            st.markdown("**Trả lời**")
            st.markdown(r["text"] or "_(trống — model chỉ gọi tool)_")
            if r["tool_events"]:
                with st.expander("Kết quả tool"):
                    st.json(r["tool_events"])

    if st.button("💾 Lưu kết quả so sánh vào analysis/"):
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        out = ANALYSIS_DIR / f"answer_compare_{datetime.now():%Y%m%dT%H%M%S}.json"
        out.write_text(json.dumps(cmp_, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        st.success(f"Đã lưu {out.relative_to(ROOT)}")


def page_telegram(cfg: dict[str, Any]) -> None:
    st.title("📨 Telegram")

    # Không hiển thị token / chat id lên UI (UI có thể được share qua link public).
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.getenv(k)]
    if missing:
        st.warning("Chưa cấu hình Telegram trong `.env`: " + ", ".join(f"`{k}`" for k in missing))

    # ---- A. Gửi bản tin lên kênh ----
    st.subheader("A. Gửi bản tin lên kênh")
    st.caption("Gọi đúng tool `send` của agent. Chỉ gửi khi bạn tick xác nhận → `confirmed=True`.")
    text = st.text_area("Nội dung bản tin", height=180, key="tg_page_text",
                        placeholder="Dán bản tin hoặc copy câu trả lời từ trang Chat…")
    ok = st.checkbox("Tôi xác nhận gửi nội dung này lên kênh Telegram", key="tg_page_confirm")
    if st.button("📤 Gửi lên kênh", disabled=not (ok and text.strip())):
        res = send_to_telegram(text)
        (st.success if res.get("status") == "sent" else st.error)(json.dumps(res, ensure_ascii=False))

    # ---- B. Bot chat ----
    st.subheader("B. Bot chat Telegram")
    st.caption("Người dùng nhắn tin cho bot trên Telegram → bot chạy agent và trả lời. Mỗi chat có transcript riêng trong `transcripts/`.")
    holder = bot_holder()
    if bot_running():
        st.success(f"Bot đang chạy (từ {holder['started_at']}): `{holder['cmd']}`")
        if st.button("⏹ Dừng bot"):
            stop_bot()
            st.rerun()
    else:
        st.info(f"Bot đang tắt. Bấm Start sẽ chạy với version **{cfg['label']}** và provider **{cfg['provider']}** (chọn ở sidebar).")
        if st.button("▶️ Start bot", disabled=not os.getenv("TELEGRAM_BOT_TOKEN")):
            start_bot(cfg["provider"], cfg["version_choice"], cfg["label"])
            st.rerun()
    l1, l2 = st.columns(2)
    l1.button("🔄 Làm mới log", **STRETCH)
    if l2.button("🗑 Xoá log cũ", **STRETCH) and BOT_LOG.exists():
        BOT_LOG.write_text("", encoding="utf-8")
    st.code(tail(BOT_LOG), language="text")


# ======================================================================
# Main
# ======================================================================
st.set_page_config(page_title="Research Agent", page_icon="💬", layout="wide")
if "messages" not in st.session_state:
    new_conversation()

locked = bool(st.session_state.messages)  # khoá cấu hình sau khi đã chat
with st.sidebar:
    page = st.radio("Trang", ["💬 Chat", "📊 So sánh version", "🆚 So sánh trả lời", "📨 Telegram"], label_visibility="collapsed")
    st.divider()

    st.markdown("**Cấu hình agent**")
    provider_name = st.selectbox("Provider", PROVIDERS, disabled=locked)
    model = st.text_input("Model (để trống = mặc định)", disabled=locked) or None
    versions = list_versions()
    options = version_options()
    version_choice = st.selectbox("Version (prompt + tools)", options, index=default_version_index(options),
                                  format_func=version_label, disabled=locked,
                                  help="Snapshot trong artifacts/versions/. '(hiện tại)' = giống file đang dùng trong artifacts/.")
    if version_choice == CURRENT:
        label = st.text_input("Nhãn version cho transcript", value=f"v{len(versions)}", disabled=locked)
    else:
        label = version_choice
    prompt_path, tools_path = version_paths(version_choice)
    av = build_artifact_version(label, prompt_path, tools_path)
    st.caption(f"`{av.artifact_version}`")
    window = st.number_input("History window (cặp user/assistant)", 0, 20, 5, disabled=locked)
    max_rounds = st.number_input("Max tool rounds", 1, 10, 4, disabled=locked)

    st.button("➕ Cuộc hội thoại mới", on_click=new_conversation, **STRETCH)
    if st.button("🔄 Reload prompt/tools", **STRETCH):
        load_artifacts.clear()
        st.rerun()
    if st.session_state.transcript_path:
        st.caption(f"Transcript: `{st.session_state.transcript_path.name}`")

    with st.expander("💾 Lưu snapshot version hiện tại"):
        snap = st.text_input("Tên version", value=f"v{len(versions)}" if versions else "v0", key="snap_label")
        exists = (VERSIONS_DIR / snap).exists()
        overwrite = st.checkbox("Ghi đè", value=False, disabled=not exists, key="snap_over")
        if st.button("Lưu artifacts/ → versions/" + snap, disabled=exists and not overwrite):
            st.success(f"Đã lưu {save_snapshot(snap)}")
            st.rerun()

    if bot_running():
        st.caption("🤖 Bot Telegram đang chạy")

cfg = {
    "provider": provider_name, "model": model, "version_choice": version_choice, "label": label,
    "prompt_path": prompt_path, "tools_path": tools_path, "artifact_version": av.artifact_version,
    "window": int(window), "max_rounds": int(max_rounds),
}

if page == "💬 Chat":
    page_chat(cfg)
elif page == "📊 So sánh version":
    page_compare()
elif page == "🆚 So sánh trả lời":
    page_answers(cfg)
else:
    page_telegram(cfg)