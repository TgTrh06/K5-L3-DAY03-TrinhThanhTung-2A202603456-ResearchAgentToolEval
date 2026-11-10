"""Tab so sánh eval giữa các version (đọc các file run trong thư mục runs/).

Dùng từ app.py:
    from compare_tab import render_compare_tab
    render_compare_tab(runs_dir, artifacts_dir)

Mỗi file run là JSON do eval runner sinh ra (có "summary", "results",
"prompt_hash", "tools_hash", ...). Tab này:
  1. Liệt kê mọi run + metric tổng.
  2. So sánh 2 run: delta metric, case nào fixed / regressed / đổi hành vi.
  3. Cho thấy THAY ĐỔI giữa 2 version: model/provider/dataset, hash prompt/tools,
     và diff nội dung prompt/tools khi tìm được snapshot khớp hash.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import json
from pathlib import Path
from typing import Any

import streamlit as st

import version_store as vs

LOG_FIELDS = [
    "version", "author", "changed_artifact", "artifact_version", "prompt_hash", "tools_hash",
    "reason", "hypothesis", "metric_before", "metric_after", "run_file",
]

METRICS = [
    ("case_accuracy", "Case accuracy"),
    ("tool_routing_accuracy", "Tool routing"),
    ("argument_accuracy", "Argument"),
    ("multiturn_accuracy", "Multi-turn"),
]


# ---------- load ----------
def load_runs(runs_dir: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return runs
    for path in sorted(runs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "results" not in data or "summary" not in data:
            continue
        data["_file"] = path.name
        data["_path"] = str(path)
        runs.append(data)
    runs.sort(key=lambda r: r.get("generated_at") or "", reverse=True)  # mới nhất trước
    return runs


def run_label(r: dict[str, Any]) -> str:
    acc = r.get("summary", {}).get("case_accuracy")
    acc_s = f"{acc:.0%}" if isinstance(acc, (int, float)) else "n/a"
    return (
        f"v{r.get('version')} · {r.get('phase')}/{r.get('suite')} · "
        f"{r.get('provider')}/{r.get('model')} · {r.get('generated_at')} · {acc_s}"
    )


# ---------- helpers ----------
def fmt_calls(result: dict[str, Any]) -> str:
    calls = result.get("actual_tool_calls") or []
    if not calls:
        text = (result.get("actual_text") or "").strip().replace("\n", " ")
        return f"(no tool) {text[:80]}" if text else "(no tool)"
    return "; ".join(
        f"{c.get('name')}({json.dumps(c.get('args', {}), ensure_ascii=False)})" for c in calls
    )


def case_status(a: dict[str, Any] | None, b: dict[str, Any] | None) -> str:
    if a is None:
        return "🆕 Chỉ có ở B"
    if b is None:
        return "➖ Chỉ có ở A"
    pa, pb = a["result"]["passed"], b["result"]["passed"]
    if not pa and pb:
        return "✅ Fixed"
    if pa and not pb:
        return "❌ Regressed"
    return "Pass → Pass" if pa else "Fail → Fail"


def sha_candidates(raw: bytes) -> set[str]:
    norm = raw.replace(b"\r\n", b"\n")
    return {hashlib.sha256(raw).hexdigest(), hashlib.sha256(norm).hexdigest()}


def find_artifact_text(run: dict[str, Any], kind: str, artifacts_dir: Path) -> str | None:
    """Tìm nội dung prompt/tools khớp hash của run. kind: 'prompt' | 'tools'."""
    want = run.get("prompt_hash" if kind == "prompt" else "tools_hash")
    fname = "system_prompt.md" if kind == "prompt" else "tools.yaml"
    recorded = run.get("system_prompt" if kind == "prompt" else "tools")
    ver = str(run.get("version"))
    # 1) snapshot đã lưu bằng version_store: khớp theo hash ghi trong meta.json
    if want:
        for meta in vs.list_versions(artifacts_dir):
            if meta.get("prompt_hash" if kind == "prompt" else "tools_hash") == want:
                p = Path(meta["_dir"]) / fname
                if p.is_file():
                    return p.read_text(encoding="utf-8")
    cands: list[Path] = []
    if recorded:
        cands.append(Path(recorded))
    for base in (artifacts_dir, artifacts_dir.parent):
        cands += [
            base / "versions" / ver / fname,
            base / "versions" / f"v{ver}" / fname,
            base / f"v{ver}" / fname,
            base / ver / fname,
        ]
    cands.append(artifacts_dir / fname)  # bản hiện tại (chỉ dùng nếu khớp hash)
    for p in cands:
        try:
            if p.is_file():
                raw = p.read_bytes()
                if want and want in sha_candidates(raw):
                    return raw.decode("utf-8")
        except OSError:
            continue
    return None


def diff_text(a: str, b: str, na: str, nb: str) -> str:
    return "".join(
        difflib.unified_diff(
            a.splitlines(keepends=True), b.splitlines(keepends=True), fromfile=na, tofile=nb
        )
    )


def delta_str(a: float | None, b: float | None) -> str | None:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return None
    return f"{(b - a) * 100:+.1f} pp"


# ---------- sections ----------
def _overview(runs: list[dict[str, Any]]) -> None:
    rows = []
    for r in runs:
        s = r["summary"]
        rows.append({
            "version": r.get("version"),
            "phase/suite": f"{r.get('phase')}/{r.get('suite')}",
            "provider": r.get("provider"),
            "model": r.get("model"),
            "generated_at": r.get("generated_at"),
            "passed": f"{s.get('passed_cases')}/{s.get('total_cases')}",
            **{label: s.get(key) for key, label in METRICS},
            "prompt": (r.get("prompt_hash") or "")[:8],
            "tools": (r.get("tools_hash") or "")[:8],
            "file": r["_file"],
        })
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            label: st.column_config.ProgressColumn(label, min_value=0.0, max_value=1.0, format="%.2f")
            for _, label in METRICS
        },
    )


def _metrics(a: dict[str, Any], b: dict[str, Any]) -> None:
    sa, sb = a["summary"], b["summary"]
    cols = st.columns(len(METRICS))
    for col, (key, label) in zip(cols, METRICS):
        va, vb = sa.get(key), sb.get(key)
        col.metric(
            label,
            f"{vb:.0%}" if isinstance(vb, (int, float)) else "n/a",
            delta=delta_str(va, vb),
        )
    fa, fb = sa.get("failure_counts", {}), sb.get("failure_counts", {})
    oa, ob = sa.get("observed_mismatch_counts", {}), sb.get("observed_mismatch_counts", {})
    rows = []
    for group, ca, cb in (("failure_type", fa, fb), ("observed_mismatch", oa, ob)):
        for k in sorted(set(ca) | set(cb)):
            va, vb = ca.get(k, 0), cb.get(k, 0)
            rows.append({"nhóm": group, "loại": k, "A": va, "B": vb, "Δ": vb - va})
    if rows:
        st.caption("Số lỗi theo loại (giảm = tốt)")
        st.dataframe(rows, use_container_width=True, hide_index=True)


def _case_diff(a: dict[str, Any], b: dict[str, Any]) -> None:
    ra = {c["id"]: c for c in a["results"]}
    rb = {c["id"]: c for c in b["results"]}
    ids = list(dict.fromkeys([*ra, *rb]))

    rows, detail = [], {}
    for cid in ids:
        ca, cb = ra.get(cid), rb.get(cid)
        status = case_status(ca, cb)
        ta = fmt_calls(ca["result"]) if ca else "—"
        tb = fmt_calls(cb["result"]) if cb else "—"
        behavior_changed = bool(ca and cb and ta != tb)
        rows.append({
            "case": cid,
            "trạng thái": status,
            "đổi hành vi": "🔀" if behavior_changed else "",
            "A": ta,
            "B": tb,
        })
        detail[cid] = (ca, cb, status, behavior_changed)

    n = lambda s: sum(1 for r in rows if r["trạng thái"] == s)  # noqa: E731
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✅ Fixed", n("✅ Fixed"))
    c2.metric("❌ Regressed", n("❌ Regressed"))
    c3.metric("Fail → Fail", n("Fail → Fail"))
    c4.metric("🔀 Đổi hành vi", sum(1 for r in rows if r["đổi hành vi"]))

    only_changed = st.checkbox("Chỉ hiện case có thay đổi (fixed / regressed / đổi hành vi)", value=True)
    shown = [
        r for r in rows
        if not only_changed
        or r["trạng thái"] in ("✅ Fixed", "❌ Regressed", "🆕 Chỉ có ở B", "➖ Chỉ có ở A")
        or r["đổi hành vi"]
    ]
    if not shown:
        st.info("Không có case nào thay đổi giữa hai run.")
        return
    st.dataframe(shown, use_container_width=True, hide_index=True)

    st.caption("Chi tiết từng case")
    for r in shown:
        ca, cb, status, _ = detail[r["case"]]
        with st.expander(f"{status} · {r['case']}"):
            sample = (cb or ca)
            if sample:
                st.markdown(f"**Input:** `{json.dumps(sample['input'], ensure_ascii=False)}`")
                st.markdown(f"**Expect:** `{json.dumps(sample['expect'], ensure_ascii=False)}`")
            left, right = st.columns(2)
            for col, tag, c in ((left, "A", ca), (right, "B", cb)):
                with col:
                    st.markdown(f"**{tag}**")
                    if c is None:
                        st.write("— không có —")
                        continue
                    res = c["result"]
                    st.write("passed" if res["passed"] else "failed")
                    st.code(fmt_calls(res), language="text")
                    if res.get("failures"):
                        st.markdown("\n".join(f"- {f}" for f in res["failures"]))


def _changes(a: dict[str, Any], b: dict[str, Any], artifacts_dir: Path) -> None:
    fields = [
        ("version", "version"),
        ("artifact_version", "artifact_version"),
        ("provider", "provider"),
        ("model", "model"),
        ("dataset_id", "dataset_id"),
        ("prompt_hash", "system prompt (hash)"),
        ("tools_hash", "tools.yaml (hash)"),
    ]
    rows = []
    for key, label in fields:
        va, vb = a.get(key), b.get(key)
        if key.endswith("_hash"):
            va, vb = (va or "")[:12], (vb or "")[:12]
        rows.append({"thành phần": label, "A": va, "B": vb, "đổi?": "✏️ Đổi" if va != vb else ""})
    st.dataframe(rows, use_container_width=True, hide_index=True)

    if a.get("dataset_id") != b.get("dataset_id"):
        st.warning("Hai run dùng dataset khác nhau, so sánh case có thể không công bằng.")

    for kind, title, lang in (("prompt", "System prompt", "markdown"), ("tools", "Tools", "yaml")):
        key = "prompt_hash" if kind == "prompt" else "tools_hash"
        with st.expander(f"Diff {title}", expanded=a.get(key) != b.get(key)):
            if a.get(key) == b.get(key):
                st.caption("Không đổi.")
                continue
            ta = find_artifact_text(a, kind, artifacts_dir)
            tb = find_artifact_text(b, kind, artifacts_dir)
            if ta is None or tb is None:
                missing = " và ".join(t for t, x in (("A", ta), ("B", tb)) if x is None)
                st.info(
                    f"Hash đã đổi nhưng không tìm được bản {title.lower()} khớp hash của {missing} "
                    f"(run chỉ lưu hash, không lưu nội dung). Lưu snapshot vào "
                    f"`{artifacts_dir}/versions/<version>/` để xem được diff."
                )
                continue
            d = diff_text(ta, tb, f"A (v{a.get('version')})", f"B (v{b.get('version')})")
            st.code(d or "(không có khác biệt nội dung, chỉ khác định dạng)", language="diff")


# ---------- export version_log.csv ----------
def metrics_str(run: dict[str, Any], keys: list[str]) -> str:
    """'case_accuracy=0.6500; tool_routing_accuracy=0.7500' (bỏ metric không có giá trị)."""
    summ = run.get("summary", {})
    return "; ".join(
        f"{k}={summ[k]:.4f}" for k in keys if isinstance(summ.get(k), (int, float))
    )


def build_log_row(
    a: dict[str, Any],
    b: dict[str, Any],
    author: str,
    reason: str,
    hypothesis: str,
    metric_keys: list[str],
) -> dict[str, str]:
    """Một dòng version_log: B là version mới, A là baseline (metric_before)."""
    if a.get("prompt_hash") and b.get("prompt_hash") and a.get("tools_hash") and b.get("tools_hash"):
        changed = vs.changed_label(
            a["prompt_hash"] != b["prompt_hash"], a["tools_hash"] != b["tools_hash"]
        )
    else:
        changed = "unknown"
    return {
        "version": str(b.get("version", "")),
        "author": author.strip(),
        "changed_artifact": changed,
        "artifact_version": str(b.get("artifact_version") or ""),
        "prompt_hash": str(b.get("prompt_hash") or ""),
        "tools_hash": str(b.get("tools_hash") or ""),
        "reason": reason.strip(),
        "hypothesis": hypothesis.strip(),
        "metric_before": metrics_str(a, metric_keys),
        "metric_after": metrics_str(b, metric_keys),
        "run_file": str(b.get("_file", "")),
    }


def read_log(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_log_row(path: Path, row: dict[str, str]) -> bool:
    """Ghi/cập nhật dòng (trùng artifact_version + run_file thì thay). Trả về True nếu là thay thế."""
    rows = read_log(path)
    replaced = False
    for i, r in enumerate(rows):
        if r.get("artifact_version") == row["artifact_version"] and r.get("run_file") == row["run_file"]:
            rows[i], replaced = row, True
            break
    if not replaced:
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig để Excel đọc đúng tiếng Việt
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return replaced


def _export(a: dict[str, Any], b: dict[str, Any], artifacts_dir: Path, log_path: Path) -> None:
    st.caption(
        "Ghi một dòng vào version_log.csv: B là version mới, metric_before lấy từ A, "
        "metric_after lấy từ B."
    )
    meta = vs.find_meta_for_run(artifacts_dir, b) or {}
    c1, c2 = st.columns(2)
    author = c1.text_input("author", value=meta.get("author", ""), key=f"exp_author_{b['_file']}")
    metric_keys = c2.multiselect(
        "Metric xuất", [k for k, _ in METRICS], default=[k for k, _ in METRICS],
        format_func=dict(METRICS).get, key="exp_metrics",
    )
    reason = st.text_area("reason", value=meta.get("reason", ""), key=f"exp_reason_{b['_file']}")
    hypothesis = st.text_area("hypothesis", value=meta.get("hypothesis", ""), key=f"exp_hyp_{b['_file']}")

    row = build_log_row(a, b, author, reason, hypothesis, metric_keys)
    st.caption("Dòng sẽ được ghi")
    st.dataframe([row], use_container_width=True, hide_index=True)
    if a["_file"] == b["_file"]:
        st.warning("A và B là cùng một run, metric_before = metric_after.")

    if st.button("📤 Ghi vào version_log.csv", type="primary"):
        replaced = write_log_row(log_path, row)
        st.success(f"{'Đã cập nhật' if replaced else 'Đã thêm'} dòng vào `{log_path}`")

    rows = read_log(log_path)
    if rows:
        with st.expander(f"Nội dung version_log.csv ({len(rows)} dòng)", expanded=False):
            st.dataframe(rows, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Tải version_log.csv", log_path.read_bytes(), file_name="version_log.csv", mime="text/csv"
        )


# ---------- entry ----------
def render_compare_tab(runs_dir: Path, artifacts_dir: Path, log_path: Path | None = None) -> None:
    log_path = log_path or (runs_dir.parent / "version_log.csv")
    head, btn = st.columns([5, 1])
    head.subheader("So sánh eval giữa các version")
    if btn.button("🔄 Tải lại", use_container_width=True):
        st.rerun()

    runs = load_runs(runs_dir)
    if not runs:
        st.info(f"Chưa có file run nào trong `{runs_dir}`. Chạy eval và đặt file kết quả vào thư mục này.")
        return

    st.caption(f"{len(runs)} run trong `{runs_dir}`")
    with st.expander("Tất cả run", expanded=False):
        _overview(runs)

    if len(runs) < 2:
        st.info("Cần ít nhất 2 run để so sánh.")
        return

    labels = {r["_file"]: run_label(r) for r in runs}
    files = list(labels)
    c1, c2 = st.columns(2)
    fa = c1.selectbox("A (baseline)", files, index=min(1, len(files) - 1), format_func=labels.get, key="cmp_a")
    fb = c2.selectbox("B (so sánh)", files, index=0, format_func=labels.get, key="cmp_b")
    a = next(r for r in runs if r["_file"] == fa)
    b = next(r for r in runs if r["_file"] == fb)
    if fa == fb:
        st.warning("A và B đang là cùng một run.")

    t_metrics, t_cases, t_changes, t_export = st.tabs(
        ["📊 Metric", "🧪 Từng case", "🧩 Thay đổi version", "📤 Xuất version_log"]
    )
    with t_metrics:
        _metrics(a, b)
    with t_cases:
        _case_diff(a, b)
    with t_changes:
        _changes(a, b, artifacts_dir)
    with t_export:
        _export(a, b, artifacts_dir, log_path)
