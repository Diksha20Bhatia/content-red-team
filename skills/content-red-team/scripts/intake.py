#!/usr/bin/env python3
"""Normalise review inputs (text/md/pdf/docx/images) into one inputs.json.

Examples:
  intake.py --project "PM interview video" --title "Title A" --title "Title B" \
            --thumbnail thumbA.png --thumb-text "STOP DOING THIS" --script script.md \
            --brief brief.md --format long --audience "aspiring PMs" --out work/
Any --title/--script/--brief value that is an existing file path is read from disk,
otherwise it is treated as pasted text. Repeat --title / --thumbnail for A/B/C variants.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thumb_preview import make_previews  # noqa: E402

TEXT_EXT = {".txt", ".md", ".markdown", ".text", ""}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
FORMATS = {"long", "short", "webinar"}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "project"


def read_docx(p: Path) -> str:
    """Dependency-free .docx text extraction (paragraphs joined by newlines)."""
    with zipfile.ZipFile(p) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paras = ["".join(t.text or "" for t in para.iter(f"{ns}t")) for para in root.iter(f"{ns}p")]
    return "\n".join(paras)


def read_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise SystemExit("PDF input needs pypdf: pip install pypdf (or paste the text)") from e
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)


def read_any(value: str) -> tuple[str, str | None]:
    """Return (text, source path or None)."""
    p = Path(value).expanduser()
    try:
        is_file = p.is_file()
    except OSError:  # long pasted text is not a valid path
        is_file = False
    if not is_file:
        return value, None
    ext = p.suffix.lower()
    if ext == ".docx":
        return read_docx(p), str(p)
    if ext == ".pdf":
        return read_pdf(p), str(p)
    if ext in TEXT_EXT:
        return p.read_text(errors="replace"), str(p)
    raise SystemExit(f"unsupported file type {ext} for {p} (use md/txt/pdf/docx)")


def labels(n: int) -> list[str]:
    return [chr(ord("A") + i) for i in range(n)]


def build(args: argparse.Namespace) -> dict:
    out = Path(args.out)
    assumptions: list[str] = []
    missing: list[str] = []

    raw: list[str] = []
    for t in args.title:
        text, src = read_any(t)
        # a file holds one title per line; pasted text is a single title
        raw += [ln.strip() for ln in text.splitlines() if ln.strip()] if src else [text.strip()]
    titles = [{"label": lab, "text": t} for lab, t in zip(labels(len(raw)), raw)]
    if not titles:
        missing.append("title")

    thumbs = []
    texts = list(args.thumb_text or [])
    for lab, img in zip(labels(len(args.thumbnail)), args.thumbnail):
        p = Path(img).expanduser()
        if p.suffix.lower() not in IMG_EXT:
            raise SystemExit(f"thumbnail must be png/jpg/webp: {img}")
        info = make_previews(p, out / "thumbs", lab)
        i = ord(lab) - 65
        info["text"] = texts[i] if i < len(texts) else ""
        if not info["text"]:
            assumptions.append(f"No text supplied for thumbnail {lab}; reviewers read it from the image.")
        thumbs.append(info)
    if not thumbs:
        assumptions.append("No thumbnail supplied: thumbnail review is skipped.")

    script = None
    if args.script:
        text, src = read_any(args.script)
        script = {"path": src, "text": text.strip(), "words": len(text.split())}
    else:
        missing.append("script")

    brief = read_any(args.brief)[0].strip() if args.brief else None
    fmt = (args.format or "").lower() or None
    if fmt and fmt not in FORMATS:
        raise SystemExit(f"--format must be one of {sorted(FORMATS)}")
    if not fmt:
        missing.append("format")
    if not args.audience:
        assumptions.append("No target audience given: Target Viewer uses the persona default in panel.yaml.")
    if not args.goal:
        assumptions.append("No goal given: assuming reach plus audience trust.")
    if not brief:
        assumptions.append("No brief supplied: Stakeholder judges from general brand-safety and promise-vs-delivery.")

    assets = [a for a, present in (("title", titles), ("thumbnail", thumbs), ("script", script)) if present]
    return {
        "project": args.project,
        "slug": slugify(args.project),
        "created": datetime.now().strftime("%Y%m%d_%H%M"),
        "format": fmt or "long",
        "goal": args.goal or "reach plus audience trust",
        "audience": args.audience or "",
        "reference_channel": args.channel or "",
        "titles": titles,
        "thumbnails": thumbs,
        "script": script,
        "brief": brief,
        "assets": assets,
        "assumptions": assumptions,
        "missing_essential": [m for m in missing if m in ("script", "format")],
        "missing_optional": [m for m in missing if m not in ("script", "format")],
    }


def add_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--project", default="untitled")
    ap.add_argument("--title", action="append", default=[], help="text or file; repeat for variants")
    ap.add_argument("--thumbnail", action="append", default=[], help="image path; repeat for variants")
    ap.add_argument("--thumb-text", action="append", help="text on thumbnail (same order)")
    ap.add_argument("--script")
    ap.add_argument("--brief")
    ap.add_argument("--channel", help="reference channel URL")
    ap.add_argument("--audience")
    ap.add_argument("--format", help="long | short | webinar")
    ap.add_argument("--goal")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_args(ap)
    ap.add_argument("--out", default=".")
    a = ap.parse_args(argv)
    data = build(a)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inputs.json").write_text(json.dumps(data, indent=2))
    print(json.dumps({k: data[k] for k in ("project", "slug", "assets", "format", "missing_essential", "assumptions")}, indent=2))
    if data["missing_essential"]:
        print(f"NEEDS INPUT: {', '.join(data['missing_essential'])}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
