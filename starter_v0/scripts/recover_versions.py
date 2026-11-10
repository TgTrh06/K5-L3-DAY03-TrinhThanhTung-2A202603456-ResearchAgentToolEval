"""Khôi phục system_prompt.md / tools.yaml của từng version từ lịch sử lưu file của VS Code.

Mỗi run JSON trong runs/ có ghi prompt_hash và tools_hash (sha256 của file lúc chạy eval).
VS Code (và Cursor) tự lưu mỗi lần bạn Ctrl+S một file vào thư mục Local History.
Script này băm (sha256) từng file trong lịch sử đó; file nào có hash TRÙNG với run
thì chính là bản đã dùng cho version đó → copy vào artifacts/versions/<version>/.

Chạy từ starter_v0:
    python scripts/recover_versions.py              # chỉ báo cáo, không ghi gì
    python scripts/recover_versions.py --write      # ghi vào artifacts/versions/
    python scripts/recover_versions.py --search D:\\backup   # tìm thêm trong thư mục khác
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
VERSIONS = ROOT / "artifacts" / "versions"
RUN_NAME = re.compile(r"^(?P<version>[^_]+)_")
MAX_SIZE = 2_000_000  # bỏ qua file lớn hơn 2 MB


def default_search_dirs() -> list[Path]:
    dirs = [ROOT / "artifacts"]
    appdata = os.getenv("APPDATA")  # Windows
    home = Path.home()
    candidates = []
    if appdata:
        candidates += [Path(appdata) / app / "User" / "History" for app in ("Code", "Code - Insiders", "Cursor", "Windsurf")]
    candidates += [
        home / "Library/Application Support/Code/User/History",   # macOS
        home / ".config/Code/User/History",                        # Linux
    ]
    return dirs + [d for d in candidates if d.exists()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_targets() -> dict[str, dict[str, str]]:
    """version -> {"prompt": hash, "tools": hash} (run mới nhất của mỗi version)."""
    latest: dict[str, tuple[float, dict[str, str]]] = {}
    for path in RUNS.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        m = RUN_NAME.match(path.name)
        version = m.group("version") if m else str(data.get("version"))
        ph, th = str(data.get("prompt_hash") or ""), str(data.get("tools_hash") or "")
        if not ph and data.get("artifact_version"):  # dự phòng: lấy hash ngắn trong artifact_version
            parts = str(data["artifact_version"]).split("+")
            ph = next((p[1:] for p in parts if p.startswith("p")), "")
            th = next((p[1:] for p in parts if p.startswith("t")), "")
        mtime = path.stat().st_mtime
        if version not in latest or mtime > latest[version][0]:
            latest[version] = (mtime, {"prompt": ph.lower(), "tools": th.lower()})
    return {v: h for v, (_, h) in latest.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Ghi file tìm được vào artifacts/versions/")
    ap.add_argument("--search", nargs="*", default=[], help="Thư mục tìm thêm")
    args = ap.parse_args()

    targets = collect_targets()
    if not targets:
        raise SystemExit("Không đọc được run JSON nào trong runs/.")

    search_dirs = default_search_dirs() + [Path(p) for p in args.search]
    print("Tìm trong:")
    for d in search_dirs:
        print(f"  - {d}")

    # hash -> file đầu tiên có hash đó
    index: dict[str, Path] = {}
    scanned = 0
    for d in search_dirs:
        for path in d.rglob("*"):
            try:
                if not path.is_file() or path.stat().st_size > MAX_SIZE or path.name == "entries.json":
                    continue
                index.setdefault(sha256(path), path)
                scanned += 1
            except OSError:
                continue
    print(f"Đã băm {scanned} file.\n")

    def find(h: str) -> Path | None:
        if not h:
            return None
        if h in index:
            return index[h]
        return next((p for full, p in index.items() if full.startswith(h)), None)  # h là hash ngắn 12 ký tự

    missing = []
    for version in sorted(targets, key=lambda v: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", v)]):
        print(f"[{version}]")
        for kind, fname in (("prompt", "system_prompt.md"), ("tools", "tools.yaml")):
            h = targets[version][kind]
            src = find(h)
            if src is None:
                print(f"  ❌ {fname:<18} hash {h[:12] or '?'} — không tìm thấy")
                missing.append(f"{version}/{fname}")
                continue
            print(f"  ✅ {fname:<18} hash {h[:12]} ← {src}")
            if args.write:
                dest = VERSIONS / version / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
    print()
    if not args.write:
        print("Chưa ghi gì. Chạy lại với --write để lưu vào artifacts/versions/.")
    if missing:
        print("Không khôi phục được: " + ", ".join(missing))
        print("→ Với các file này, giữ bản dựng lại và ghi chú trong REPORT là 'dựng lại, không khớp hash run'.")


if __name__ == "__main__":
    main()