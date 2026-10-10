#!/usr/bin/env python3
"""Build a persona card for the reference creator from public content.

Sources tried in order (first that works wins, all optional):
  1. --from-json FILE   material an agent already pulled with a YouTube/vidIQ MCP tool:
                        {"titles": [...], "top_titles": [...], "transcripts": ["...", ...]}
  2. --from-files F...  transcripts the user pasted into text files
  3. youtube-transcript-api + yt-dlp (network), from --channel URL
If nothing can be fetched the script exits 4 and tells you to ask the user for 2-3 transcripts.

Output: <cache>/personas/<handle>.md (+ <handle>.material.json). Refreshed when older than
--max-age-days. Quotes are capped at ~15 words. Every card carries the simulation disclaimer.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

DISCLAIMER = (
    "Simulated opinion based on public content, not the real person's view. "
    "Do not invent quotes or attribute statements to the real person."
)
MAX_SNIPPET_WORDS = 15
EXIT_NEEDS_USER = 4


def snippet(text: str, n: int = MAX_SNIPPET_WORDS) -> str:
    w = text.split()
    return " ".join(w[:n]) + (" ..." if len(w) > n else "")


def fetch_titles(channel: str, limit: int = 30) -> tuple[list[str], list[str], list[str]]:
    """Return (recent titles, top titles, video ids) via yt-dlp. Empty lists when unavailable."""
    exe = shutil.which("yt-dlp")
    if not exe:
        return [], [], []
    base = channel.rstrip("/")
    try:
        r = subprocess.run([exe, "--flat-playlist", "-J", "--playlist-end", str(limit), f"{base}/videos"],
                           capture_output=True, text=True, timeout=120)
        entries = json.loads(r.stdout).get("entries", []) if r.returncode == 0 else []
        r2 = subprocess.run([exe, "--flat-playlist", "-J", "--playlist-end", "10", f"{base}/videos?view=0&sort=p"],
                            capture_output=True, text=True, timeout=120)
        top = json.loads(r2.stdout).get("entries", []) if r2.returncode == 0 else []
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return [], [], []
    return ([e["title"] for e in entries if e.get("title")],
            [e["title"] for e in top if e.get("title")],
            [e["id"] for e in entries[:5] if e.get("id")])


def fetch_transcripts(ids: list[str]) -> list[str]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return []
    out = []
    for vid in ids:
        try:
            api = YouTubeTranscriptApi()
            snippets = api.fetch(vid) if hasattr(api, "fetch") else YouTubeTranscriptApi.get_transcript(vid)
            out.append(" ".join(getattr(s, "text", None) or s["text"] for s in snippets))
        except Exception:  # noqa: BLE001 - network/captions off; skip this video
            continue
    return out


def stats(material: dict) -> dict:
    titles = material.get("titles", []) + material.get("top_titles", [])
    tr = material.get("transcripts", [])
    s: dict = {}
    if titles:
        words = [len(t.split()) for t in titles]
        s["avg_title_chars"] = round(sum(len(t) for t in titles) / len(titles))
        s["avg_title_words"] = round(sum(words) / len(words), 1)
        s["pct_titles_with_number"] = round(100 * sum(bool(re.search(r"\d", t)) for t in titles) / len(titles))
        s["pct_titles_question"] = round(100 * sum("?" in t for t in titles) / len(titles))
        s["pct_titles_allcaps_word"] = round(100 * sum(bool(re.search(r"\b[A-Z]{3,}\b", t)) for t in titles) / len(titles))
        s["common_openers"] = [w for w, _ in Counter(t.split()[0].lower() for t in titles if t.split()).most_common(3)]
    if tr:
        sentences = [x for t in tr for x in re.split(r"(?<=[.!?])\s+", t) if x.strip()]
        words = sum(len(t.split()) for t in tr) or 1
        s["avg_sentence_words"] = round(sum(len(x.split()) for x in sentences) / max(1, len(sentences)), 1)
        s["questions_per_100_words"] = round(100 * sum(t.count("?") for t in tr) / words, 1)
        s["hook_openings"] = [snippet(t, 12) for t in tr[:3]]
    return s


def heuristic_card(handle: str, material: dict) -> str:
    s = stats(material)
    lines = [
        f"<!-- persona:{handle} built {time.strftime('%Y-%m-%d')} -->",
        f"> {DISCLAIMER}",
        "",
        f"Background: Creator behind the channel `{handle}`, inferred from {len(material.get('titles', []))} recent titles, "
        f"{len(material.get('top_titles', []))} top titles and {len(material.get('transcripts', []))} transcripts.",
    ]
    if "avg_title_chars" in s:
        lines.append(
            f"Title habits (measured on the sample): ~{s['avg_title_chars']} chars / {s['avg_title_words']} words; "
            f"{s['pct_titles_with_number']}% contain a number; {s['pct_titles_question']}% are questions; "
            f"{s['pct_titles_allcaps_word']}% use an ALL-CAPS word; common openers: {', '.join(s['common_openers'])}."
        )
    if "avg_sentence_words" in s:
        lines.append(
            f"Speaking habits (measured): ~{s['avg_sentence_words']} words per sentence; "
            f"{s['questions_per_100_words']} questions per 100 words. "
            "Opening lines (short snippets): " + " | ".join(f'"{h}"' for h in s["hook_openings"])
        )
    lines += [
        "Values: Consistency with the habits above; judge whether the material fits that proven pattern.",
        "Pet peeves: Anything that departs from those habits without a reason; filler before the payoff.",
        "Voice: Infer register from the snippets above; write the review in a similar plain register without imitating exact phrases.",
        "Known bias: Favours formats that match his own sampled titles and pacing; may undervalue unfamiliar approaches.",
        "Signature questions: 1) Would this sit well next to my usual titles? 2) Where does the payoff land? 3) What would I cut?",
        "Blind spot: Judges from an established channel's position.",
    ]
    return "\n".join(lines)


def llm_card(handle: str, material: dict, base: str) -> str | None:
    """Optional upgrade with an LLM; returns None if unavailable."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from crt.config import load_panel
        from crt.llm import AnthropicLLM

        llm = AnthropicLLM(load_panel()["model"], 1500)
        text = llm.complete(
            "You write evaluator persona cards from public-content statistics. Never invent quotes. "
            f"Keep quotes under {MAX_SNIPPET_WORDS} words. Keep the disclaimer line verbatim.",
            "Improve this card using the material. Keep these headings: Background, Values, Pet peeves, Voice, "
            f"Known bias, Signature questions, Blind spot. Max 250 words.\n\nCARD:\n{base}\n\n"
            f"MATERIAL:\n{json.dumps({k: v if k != 'transcripts' else [snippet(t, 400) for t in v] for k, v in material.items()})[:12000]}",
        )
        return text if DISCLAIMER[:30] in text else DISCLAIMER_wrap(text)
    except Exception:  # noqa: BLE001
        return None


def DISCLAIMER_wrap(text: str) -> str:  # noqa: N802
    return f"> {DISCLAIMER}\n\n{text}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channel", action="append", default=[], help="channel URL (repeatable)")
    ap.add_argument("--handle", required=True, help="cache name")
    ap.add_argument("--cache-dir", default=".cache")
    ap.add_argument("--from-json")
    ap.add_argument("--from-files", nargs="*", default=[])
    ap.add_argument("--max-age-days", type=int, default=14)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--llm", action="store_true", help="polish the card with an LLM if a key is set")
    a = ap.parse_args(argv)

    out = Path(a.cache_dir) / "personas"
    card_path = out / f"{a.handle}.md"
    if card_path.exists() and not a.force and time.time() - card_path.stat().st_mtime < a.max_age_days * 86400:
        print(f"fresh cache: {card_path}")
        return 0

    material: dict = {"titles": [], "top_titles": [], "transcripts": []}
    if a.from_json:
        material.update(json.loads(Path(a.from_json).read_text()))
    if a.from_files:
        material["transcripts"] += [Path(f).read_text(errors="replace") for f in a.from_files]
    if not (material["titles"] or material["transcripts"]):
        for url in a.channel:
            t, top, ids = fetch_titles(url)
            material["titles"] += t
            material["top_titles"] += top
            material["transcripts"] += fetch_transcripts(ids)
    if not (material["titles"] or material["transcripts"]):
        print(
            "NEEDS_USER: could not fetch anything (no network, no yt-dlp/youtube-transcript-api, or no channel URL).\n"
            "Ask the user to paste 2-3 transcripts (save as files and pass --from-files) or describe the creator,\n"
            "then continue. The panel will use the generic reference-creator card until then.",
            file=sys.stderr,
        )
        return EXIT_NEEDS_USER

    base = heuristic_card(a.handle, material)
    card = (llm_card(a.handle, material, base) if a.llm else None) or base
    out.mkdir(parents=True, exist_ok=True)
    card_path.write_text(card + "\n")
    # keep only capped transcript excerpts on disk (copyright: short snippets only)
    keep = {**material, "transcripts": [snippet(t, 200) for t in material["transcripts"]]}
    (out / f"{a.handle}.material.json").write_text(json.dumps(keep, indent=2))
    print(f"wrote {card_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
