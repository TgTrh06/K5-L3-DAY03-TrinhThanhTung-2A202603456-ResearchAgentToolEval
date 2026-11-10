"""Lưu / liệt kê / chuyển đổi các version của artifact (system_prompt.md + tools.yaml).

Mỗi version là một snapshot trong  <artifacts>/versions/<tên>/ :
    system_prompt.md, tools.yaml, meta.json

"Chuyển version" = chép snapshot đó đè lên system_prompt.md / tools.yaml đang dùng.
Module này không phụ thuộc streamlit nên test được độc lập.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

PROMPT_FILE = "system_prompt.md"
TOOLS_FILE = "tools.yaml"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")


def versions_dir(artifacts_dir: Path) -> Path:
    return artifacts_dir / "versions"


def norm(name: Any) -> str:
    """'v0' và '0' coi là cùng một version."""
    return str(name or "").strip().lstrip("vV")


def changed_label(prompt_changed: bool, tools_changed: bool) -> str:
    if prompt_changed and tools_changed:
        return "system_prompt+tools"
    if prompt_changed:
        return "system_prompt"
    if tools_changed:
        return "tools"
    return "none"


def _bytes(p: Path) -> bytes | None:
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def list_versions(artifacts_dir: Path) -> list[dict[str, Any]]:
    root = versions_dir(artifacts_dir)
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for sub in root.iterdir():
        if not (sub.is_dir() and (sub / PROMPT_FILE).is_file() and (sub / TOOLS_FILE).is_file()):
            continue
        meta: dict[str, Any] = {}
        mp = sub / "meta.json"
        if mp.is_file():
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        meta["version"] = sub.name
        meta["_dir"] = str(sub)
        out.append(meta)
    out.sort(key=lambda m: (m.get("created_at") or "", m["version"]))
    return out


def find_matching_version(artifacts_dir: Path) -> str | None:
    """Tên version có snapshot trùng từng byte với prompt/tools đang dùng (None = chưa lưu)."""
    cur_p, cur_t = _bytes(artifacts_dir / PROMPT_FILE), _bytes(artifacts_dir / TOOLS_FILE)
    if cur_p is None or cur_t is None:
        return None
    match = None
    for m in list_versions(artifacts_dir):
        d = Path(m["_dir"])
        if _bytes(d / PROMPT_FILE) == cur_p and _bytes(d / TOOLS_FILE) == cur_t:
            match = m["version"]  # lấy bản mới nhất nếu trùng nhiều
    return match


def suggest_next_name(artifacts_dir: Path) -> str:
    nums = [int(n) for m in list_versions(artifacts_dir) if (n := norm(m["version"])).isdigit()]
    return f"v{max(nums) + 1}" if nums else "v0"


def save_version(
    artifacts_dir: Path,
    name: str,
    info: dict[str, Any],
    author: str = "",
    reason: str = "",
    hypothesis: str = "",
) -> dict[str, Any]:
    """Snapshot prompt/tools đang dùng thành version `name`. `info` = artifact_version_dict(...)."""
    name = name.strip()
    if not NAME_RE.match(name):
        raise ValueError("Tên version chỉ gồm chữ, số, '.', '_', '-' (tối đa 41 ký tự).")
    existing = list_versions(artifacts_dir)
    if any(norm(m["version"]) == norm(name) for m in existing):
        raise ValueError(f"Version '{name}' đã tồn tại.")
    src_p, src_t = artifacts_dir / PROMPT_FILE, artifacts_dir / TOOLS_FILE
    if not (src_p.is_file() and src_t.is_file()):
        raise FileNotFoundError(f"Thiếu {PROMPT_FILE} hoặc {TOOLS_FILE} trong {artifacts_dir}")

    parent = existing[-1] if existing else None
    if parent:
        pd = Path(parent["_dir"])
        changed = changed_label(
            _bytes(pd / PROMPT_FILE) != _bytes(src_p), _bytes(pd / TOOLS_FILE) != _bytes(src_t)
        )
    else:
        changed = "initial"

    dest = versions_dir(artifacts_dir) / name
    dest.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(src_p, dest / PROMPT_FILE)
    shutil.copyfile(src_t, dest / TOOLS_FILE)
    meta = {
        "version": name,
        "author": author.strip(),
        "reason": reason.strip(),
        "hypothesis": hypothesis.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "parent": parent["version"] if parent else None,
        "changed_artifact": changed,
        "artifact_version": info.get("artifact_version"),
        "prompt_hash": info.get("prompt_hash"),
        "tools_hash": info.get("tools_hash"),
    }
    (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def activate_version(artifacts_dir: Path, name: str) -> None:
    """Chép snapshot `name` đè lên system_prompt.md / tools.yaml đang dùng."""
    src = versions_dir(artifacts_dir) / name
    if not (src / PROMPT_FILE).is_file() or not (src / TOOLS_FILE).is_file():
        raise FileNotFoundError(f"Không tìm thấy snapshot của version '{name}'")
    shutil.copyfile(src / PROMPT_FILE, artifacts_dir / PROMPT_FILE)
    shutil.copyfile(src / TOOLS_FILE, artifacts_dir / TOOLS_FILE)


def find_meta_for_run(artifacts_dir: Path, run: dict[str, Any]) -> dict[str, Any] | None:
    """Tìm meta của version đã sinh ra một file run (theo artifact_version, hash, rồi tên)."""
    vers = list_versions(artifacts_dir)
    av = run.get("artifact_version")
    for m in vers:
        if av and m.get("artifact_version") == av:
            return m
    ph, th = run.get("prompt_hash"), run.get("tools_hash")
    if ph and th:
        for m in vers:
            if (m.get("prompt_hash"), m.get("tools_hash")) == (ph, th):
                return m
    for m in vers:
        if norm(m["version"]) == norm(run.get("version")):
            return m
    return None
