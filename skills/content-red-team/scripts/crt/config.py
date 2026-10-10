"""Load panel.yaml, rubric.yaml and persona cards. Nothing creator-specific lives here."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import yaml

SKILL_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = SKILL_DIR / "config" / "panel.yaml"
RUBRIC = SKILL_DIR / "config" / "rubric.yaml"
PERSONAS_MD = SKILL_DIR / "references" / "personas.md"
MIN_MEMBERS, MAX_MEMBERS = 3, 10
ASSETS = ("title", "thumbnail", "script")


def find_config(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    local = Path.cwd() / "content-red-team.panel.yaml"
    return local if local.exists() else DEFAULT_CONFIG


def load_panel(path: str | Path | None = None) -> dict[str, Any]:
    p = find_config(str(path) if path else None)
    cfg = yaml.safe_load(p.read_text()) or {}
    members = [m for m in cfg.get("members", []) if m.get("enabled", True)]
    if not MIN_MEMBERS <= len(members) <= MAX_MEMBERS:
        raise ValueError(f"panel needs {MIN_MEMBERS}-{MAX_MEMBERS} enabled members, got {len(members)} ({p})")
    ids = [m["id"] for m in members]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate member ids in panel config")
    for m in members:
        if not re.fullmatch(r"[a-z0-9_]+", m["id"]):
            raise ValueError(f"member id must be lowercase [a-z0-9_]: {m['id']}")
        m.setdefault("name", m["id"])
        m.setdefault("weight", 1.0)
    cfg["members"] = members
    cfg["model"] = os.environ.get("LLM_MODEL") or cfg.get("model")
    if not cfg["model"]:
        raise ValueError("no model: set LLM_MODEL or `model:` in panel.yaml")
    cfg["judge_model"] = os.environ.get("LLM_JUDGE_MODEL") or cfg.get("judge_model") or cfg["model"]
    cfg.setdefault("max_tokens", 6000)
    cfg.setdefault("max_concurrency", 8)
    cfg.setdefault("persona_cache_days", 14)
    cfg.setdefault("judge", {"id": "judge", "name": "Judge", "lens": ""})
    cfg["_path"] = str(p)
    return cfg


def load_rubric() -> dict[str, dict[str, str]]:
    return yaml.safe_load(RUBRIC.read_text())


def _md_cards() -> dict[str, str]:
    text = PERSONAS_MD.read_text()
    out: dict[str, str] = {}
    for chunk in re.split(r"^## ", text, flags=re.M)[1:]:
        head, _, body = chunk.partition("\n")
        m = re.fullmatch(r"card:([a-z0-9_]+)", head.strip())
        if m:
            out[m.group(1)] = body.split("\n---")[0].strip()
    return out


def _generic_card(m: dict[str, Any]) -> str:
    extra = " ".join(f"{k}: {m[k]}." for k in ("audience", "domain") if m.get(k))
    return (
        f"Background: {m['name']}. {extra}\nLens: {' '.join(str(m.get('lens', '')).split())}\n"
        "Voice: plain, direct, in the first person.\n"
        "Known bias: leans hard on your own lens; do not hedge toward neutrality.\n"
        "Signature questions: 1) What does my lens say is the biggest problem? "
        "2) What would I change first? 3) What would make me change my mind?"
    )


def persona_card(m: dict[str, Any], cache_dir: Path) -> tuple[str, str]:
    """Return (card text, source label). Only this member's card goes in this member's prompt."""
    if m.get("card"):
        card, src = str(m["card"]).strip(), "panel.yaml inline"
    elif m.get("card_file"):
        card, src = Path(m["card_file"]).read_text().strip(), f"file {m['card_file']}"
    else:
        cached = cache_dir / "personas" / f"{m.get('handle', m['id'])}.md"
        if cached.exists():
            card, src = cached.read_text().strip(), f"cache {cached}"
        elif m["id"] in (cards := _md_cards()):
            card, src = cards[m["id"]], "references/personas.md"
        else:
            card, src = _generic_card(m), "generated from lens"
    # per-member context from config
    ctx = " ".join(f"{k}={m[k]}" for k in ("audience", "domain") if m.get(k))
    if ctx:
        card += f"\n\nConfigured context: {ctx}"
    return card, src


def persona_is_stale(path: Path, days: int) -> bool:
    return (not path.exists()) or (time.time() - path.stat().st_mtime) > days * 86400
