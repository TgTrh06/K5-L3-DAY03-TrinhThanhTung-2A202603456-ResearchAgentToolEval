"""Tạo artifacts/version_log.csv từ các run JSON trong runs/.

Chạy từ thư mục starter_v0:
    python scripts/make_version_log.py
    python scripts/make_version_log.py --author "Tên nhóm" --suite base

Script tự lấy: version, artifact_version, prompt_hash, tools_hash, case_accuracy, run_file.
metric_before = case_accuracy của version liền trước.
Cột changed_artifact / reason / hypothesis lấy từ bảng NOTES bên dưới — SỬA lại cho đúng nhóm mình.
"""
import argparse
import csv
import json
import re
from pathlib import Path

# ---- SỬA phần này cho đúng những gì nhóm đã làm ----
NOTES = {
    "v0": {
        "changed_artifact": "none",
        "reason": "Baseline starter (prompt cố ý xấu, tool description sơ sài)",
        "hypothesis": "Đo baseline",
    },
    "v1": {
        "changed_artifact": "system_prompt.md",
        "reason": "v0 FAIL R08 R10 R11 R12 R13: agent đoán thay vì hỏi, tự gửi, ép gọi 1 tool, sai args lookup",
        "hypothesis": "Prompt starter khuyến khích đoán/gửi/ép một tool; viết lại prompt (clarify bắt buộc có response_type, quy ước args lookup, không gọi tool khi ngoài phạm vi) sẽ sửa các case này",
    },
    "v2": {
        "changed_artifact": "tools.yaml",
        "reason": "v1 còn FAIL R12 (gọi send không xác nhận) và M06",
        "hypothesis": "Tool description sơ sài nên model không biết ranh giới send/args; viết lại description (khi nào dùng/không dùng, quy ước args, send cần confirmed) sẽ sửa R12 M06",
    },
    "v3": {
        "changed_artifact": "system_prompt.md",
        "reason": "v2 còn FAIL M06 (extra_tool_call khi user bỏ Twitter chuyển sang web)",
        "hypothesis": "Rule multi-turn chỉ nói carry over, không nói bỏ nguồn cũ; thêm rule 'đổi nguồn thì chỉ gọi tool nguồn mới' sẽ sửa M06",
    },
}
# -----------------------------------------------------

HEADER = ["version", "author", "changed_artifact", "artifact_version", "prompt_hash",
          "tools_hash", "reason", "hypothesis", "metric_before", "metric_after", "run_file"]


def find_key(obj, key):
    """Tìm key ở bất kỳ độ sâu nào trong JSON (trả về giá trị đầu tiên gặp)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj[:3]:  # chỉ nhìn vài phần tử đầu, tránh quét cả results
            found = find_key(v, key)
            if found is not None:
                return found
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--suite", default="base", help="chỉ lấy run của suite này")
    ap.add_argument("--author", default="team")
    ap.add_argument("--output", default="artifacts/version_log.csv")
    ap.add_argument("--versions", nargs="*", help="chỉ ghi các version này, VD --versions v0 v1 v2 v3")
    args = ap.parse_args()

    latest = {}  # version -> (mtime, path, data)
    for path in Path(args.runs).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"Bỏ qua {path} (không đọc được JSON)")
            continue
        # Lấy version + suite từ TÊN FILE (vd v2_B_base_openrouter_...json) — đáng tin hơn
        # tìm key trong JSON (key "version" có thể xuất hiện lồng ở nhiều chỗ).
        m = re.match(r"^(?P<version>[^_]+)_[^_]+_(?P<suite>[^_]+)_", path.name)
        version = m.group("version") if m else str(find_key(data, "version"))
        suite = m.group("suite") if m else find_key(data, "suite")
        if suite and suite != args.suite:
            continue
        if args.versions and version not in args.versions:
            continue
        mtime = path.stat().st_mtime
        if version not in latest or mtime > latest[version][0]:
            latest[version] = (mtime, path, data)

    if not latest:
        raise SystemExit(f"Không tìm thấy run JSON nào của suite '{args.suite}' trong {args.runs}/")

    rows, prev_acc = [], ""
    for version in sorted(latest, key=lambda v: (len(v), v)):
        _, path, data = latest[version]
        summary = find_key(data, "summary") or {}
        acc = summary.get("case_accuracy", find_key(data, "case_accuracy"))
        note = NOTES.get(version, {})
        rows.append({
            "version": version,
            "author": args.author,
            "changed_artifact": note.get("changed_artifact", ""),
            "artifact_version": find_key(data, "artifact_version") or "",
            "prompt_hash": find_key(data, "prompt_hash") or "",
            "tools_hash": find_key(data, "tools_hash") or "",
            "reason": note.get("reason", ""),
            "hypothesis": note.get("hypothesis", ""),
            "metric_before": prev_acc,
            "metric_after": acc if acc is not None else "",
            "run_file": path.as_posix(),
        })
        prev_acc = acc if acc is not None else ""

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Đã ghi {len(rows)} dòng vào {out}")
    for r in rows:
        print(f"  {r['version']:<4} {r['metric_before']!s:>6} -> {r['metric_after']!s:<6} {r['run_file']}")


if __name__ == "__main__":
    main()