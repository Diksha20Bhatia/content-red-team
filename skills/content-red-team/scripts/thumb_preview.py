#!/usr/bin/env python3
"""Downsize a thumbnail to the sizes a phone feed shows, and measure a few pixel facts.

Usage: thumb_preview.py IMAGE [--out DIR] [--label A]
Writes <label>_1280.png, <label>_360.png, <label>_120.png and prints JSON.
Metrics are measured from pixels (not estimates), but what they *mean* is judgment.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

SIZES = (1280, 360, 120)


def _edge_density(img: Image.Image, thresh: int = 40) -> float:
    """Fraction of pixels on a strong edge: a rough clutter indicator at feed size."""
    edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
    hist = edges.histogram()
    return sum(hist[thresh + 1:]) / max(1, sum(hist))


def make_previews(path: str | Path, out_dir: str | Path, label: str = "A") -> dict:
    src = Image.open(path)
    src.load()
    rgb = src.convert("RGB")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for w in SIZES:
        h = max(1, round(rgb.height * w / rgb.width))
        im = rgb.resize((w, h), Image.LANCZOS) if w < rgb.width else rgb.copy()
        f = out / f"{label}_{w}.png"
        im.save(f)
        files[str(w)] = str(f)
    small = Image.open(files["120"])
    luma = ImageStat.Stat(rgb.convert("L"))
    q = rgb.resize((64, 64)).quantize(colors=3).convert("RGB")
    dom = max(q.getcolors(), key=lambda c: c[0])[1]
    small_luma = ImageStat.Stat(small.convert("L"))
    metrics = {
        "source_size": [rgb.width, rgb.height],
        "aspect": round(rgb.width / rgb.height, 3),
        "mean_luma": round(luma.mean[0], 1),
        "contrast_std": round(luma.stddev[0], 1),
        "dominant_hex": "#%02x%02x%02x" % dom,
        "contrast_std_120": round(small_luma.stddev[0], 1),
        "edge_density_120": round(_edge_density(small), 3),
        "note": "measured from pixels; interpretation is judgment",
    }
    return {"label": label, "path": str(path), "previews": files, "metrics": metrics}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image")
    ap.add_argument("--out", default="thumbs")
    ap.add_argument("--label", default="A")
    a = ap.parse_args(argv)
    try:
        print(json.dumps(make_previews(a.image, a.out, a.label), indent=2))
    except (OSError, ValueError) as e:
        print(f"error: cannot read image {a.image}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
