"""Chạy và chấm eval cho Research Agent. Không phụ thuộc Streamlit.

Quy ước chấm (xấp xỉ theo mô tả trong eval_base.json: "tool_calls + args (subset)"):
- expect.tool_calls: mỗi call mong đợi phải khớp với MỘT call thực tế cùng tên, trong đó
  mọi arg mong đợi đều khớp (subset; arg thừa không sao). Không phụ thuộc thứ tự call.
  So khớp chuỗi: bỏ khoảng trắng/'@'/'/' cuối, không phân biệt hoa thường; riêng `query`
  mặc định là "chứa" (strict_query=True thì phải bằng). Số so theo giá trị.
- expect.no_tool: không được gọi tool nào. (`behavior` không chấm tự động.)
- Case nhiều lượt: chạy lần lượt từng lượt user (có lịch sử), chỉ chấm tool call của LƯỢT CUỐI.
- Call thừa không làm trượt case, nhưng được ghi lại trong `extra`.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable


# ---------- nạp dataset ----------
def parse_dataset(obj: Any, fallback_id: str = "eval") -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(obj, dict) or not isinstance(obj.get("cases"), list):
        raise ValueError("File eval cần có khóa `cases` là một danh sách.")
    ds = str(obj.get("dataset_id") or fallback_id)
    cases = []
    for c in obj["cases"]:
        if isinstance(c, dict) and c.get("id"):
            cases.append({**c, "_dataset": ds})
    return ds, cases


def load_dataset_file(path: Path) -> tuple[str, list[dict[str, Any]]]:
    return parse_dataset(json.loads(Path(path).read_text(encoding="utf-8")), Path(path).stem)


def case_turns(case: dict[str, Any]) -> list[dict[str, str]]:
    if isinstance(case.get("turns"), list):
        return [{"role": t.get("role", "user"), "content": str(t.get("content", ""))} for t in case["turns"]]
    if case.get("query"):
        return [{"role": "user", "content": str(case["query"])}]
    return []


# ---------- chấm ----------
def _norm(s: str) -> str:
    return s.strip().lstrip("@").rstrip("/").lower()


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def arg_matches(key: str, expected: Any, actual: Any, *, strict_query: bool = False) -> bool:
    if isinstance(expected, str):
        if not isinstance(actual, str):
            return False
        e, a = _norm(expected), _norm(actual)
        return e == a if (strict_query or key != "query") else e in a
    if _is_num(expected):
        if isinstance(actual, str):
            try:
                actual = float(actual)
            except ValueError:
                return False
        return _is_num(actual) and float(expected) == float(actual)
    return expected == actual


def score_case(case: dict[str, Any], calls: list[dict[str, Any]], *, strict_query: bool = False) -> dict[str, Any]:
    expect = case.get("expect") or {}
    if "tool_calls" in expect:
        used: set[int] = set()
        checks = []
        for exp in expect["tool_calls"]:
            name, eargs = exp.get("name"), exp.get("args") or {}
            matched_idx, best, best_bad = None, None, None
            for i, call in enumerate(calls):
                if i in used or call["name"] != name:
                    continue
                cargs = call.get("args") or {}
                bad = {k: {"expected": v, "got": cargs.get(k)} for k, v in eargs.items()
                       if k not in cargs or not arg_matches(k, v, cargs[k], strict_query=strict_query)}
                if not bad:
                    matched_idx = i
                    break
                if best is None or len(bad) < len(best_bad or {}):
                    best, best_bad = call, bad
            if matched_idx is not None:
                used.add(matched_idx)
                checks.append({"expected": exp, "matched": True})
            else:
                checks.append({"expected": exp, "matched": False, "called": best is not None,
                               "got": best, "bad_args": best_bad or {}})
        extra = [c["name"] for i, c in enumerate(calls) if i not in used]
        return {"kind": "tool_calls", "passed": all(c["matched"] for c in checks),
                "checks": checks, "extra": extra}
    if expect.get("no_tool"):
        return {"kind": "no_tool", "passed": not calls, "checks": [],
                "extra": [c["name"] for c in calls], "behavior": expect.get("behavior")}
    return {"kind": "unscored", "passed": None, "checks": [], "extra": []}


def explain(rec: dict[str, Any]) -> list[str]:
    """Các dòng giải thích vì sao case trượt (hoặc đạt)."""
    if rec.get("error"):
        return [f"Lỗi khi chạy: {rec['error']}"]
    sc = rec["score"]
    if sc["kind"] == "unscored":
        return ["Case có `expect` chưa được hỗ trợ — không chấm."]
    out: list[str] = []
    if sc["kind"] == "no_tool":
        if sc["passed"]:
            return ["Không gọi tool (đúng)."]
        return [f"Phải KHÔNG gọi tool nhưng đã gọi: {', '.join(sc['extra'])}."]
    for c in sc["checks"]:
        name = c["expected"].get("name")
        if c["matched"]:
            out.append(f"✔ `{name}` khớp.")
        elif not c.get("called"):
            out.append(f"✘ Không gọi `{name}`.")
        else:
            diffs = "; ".join(f"{k}: cần {v['expected']!r}, nhận {v['got']!r}" for k, v in c["bad_args"].items())
            out.append(f"✘ `{name}` sai args — {diffs}")
    if sc["extra"]:
        out.append(f"(call thừa, không tính lỗi: {', '.join(sc['extra'])})")
    return out


# ---------- chạy ----------
StepFn = Callable[[list[dict[str, str]], str], dict[str, Any]]


def run_case(case: dict[str, Any], step: StepFn, *, strict_query: bool = False) -> dict[str, Any]:
    """step(history, user_text) -> kết quả của chat.run_model_tool_loop."""
    rec: dict[str, Any] = {
        "id": case["id"], "dataset": case.get("_dataset"),
        "failure_type": case.get("failure_type"),
        "skill": (case.get("metadata") or {}).get("skill"),
        "difficulty": (case.get("metadata") or {}).get("difficulty"),
        "expect": case.get("expect"), "turns": [], "calls": [], "status": None,
        "answer": None, "error": None, "passed": None,
    }
    history: list[dict[str, str]] = []
    result: dict[str, Any] | None = None
    try:
        for t in case_turns(case):
            if t["role"] != "user":
                history.append({"role": t["role"], "content": t["content"]})
                continue
            result = step(history, t["content"])
            history += [{"role": "user", "content": t["content"]},
                        {"role": "assistant", "content": result["assistant_text"]}]
            rec["turns"].append({
                "user": t["content"], "status": result["status"], "answer": result["assistant_text"],
                "tools": [e.get("tool") for e in result.get("tool_events", [])],
            })
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["passed"] = False
        rec["score"] = {"kind": "error", "passed": False, "checks": [], "extra": []}
        return rec
    if result is None:
        rec["error"] = "Case không có lượt user nào."
        rec["passed"] = None
        rec["score"] = {"kind": "unscored", "passed": None, "checks": [], "extra": []}
        return rec
    rec["calls"] = [{"name": e.get("tool"), "args": e.get("args") or {}} for e in result.get("tool_events", [])]
    rec["status"], rec["answer"] = result["status"], result["assistant_text"]
    rec["score"] = score_case(case, rec["calls"], strict_query=strict_query)
    rec["passed"] = rec["score"]["passed"]
    return rec


def run_many(jobs: list[tuple[Any, Callable[[], Any]]], workers: int = 1,
             on_done: Callable[[int, int], None] | None = None) -> dict[Any, Any]:
    """Chạy các job (key, fn) song song; on_done(done, total) được gọi ở luồng chính."""
    out: dict[Any, Any] = {}
    total = len(jobs)
    if workers <= 1:
        for i, (key, fn) in enumerate(jobs, 1):
            out[key] = fn()
            on_done and on_done(i, total)
        return out
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn): key for key, fn in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            out[futs[f]] = f.result()
            on_done and on_done(i, total)
    return out


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in records if r["passed"] is not None]
    passed = sum(1 for r in scored if r["passed"])

    def group(key: str) -> dict[str, list[int]]:
        g: dict[str, list[int]] = {}
        for r in scored:
            p = g.setdefault(str(r.get(key) or "?"), [0, 0])
            p[0] += 1 if r["passed"] else 0
            p[1] += 1
        return g

    return {
        "passed": passed, "scored": len(scored), "total": len(records),
        "rate": round(passed / len(scored), 4) if scored else None,
        "by_failure_type": group("failure_type"), "by_difficulty": group("difficulty"),
    }
