"""Regenerates examples/sample_input/thumbnail.png (a generic placeholder thumbnail)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(__file__).resolve().parents[2] / "examples" / "sample_input" / "thumbnail.png"
im = Image.new("RGB", (1280, 720))
d = ImageDraw.Draw(im)
for y in range(720):
    d.line([(0, y), (1280, y)], fill=(24 + y // 12, 32 + y // 18, 64 + y // 10))
try:
    big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 150)
    small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 54)
except OSError:
    big = small = ImageFont.load_default()
d.ellipse((120, 200, 520, 600), fill=(240, 200, 160))
d.ellipse((220, 330, 260, 370), fill=(30, 30, 30))
d.ellipse((380, 330, 420, 370), fill=(30, 30, 30))
d.arc((240, 420, 400, 540), 20, 160, fill=(120, 40, 40), width=10)
d.text((560, 170), "STOP", font=big, fill=(255, 220, 40))
d.text((560, 330), "MEMORISING", font=big, fill=(255, 255, 255))
d.text((560, 520), "PM frameworks (do this instead)", font=small, fill=(170, 190, 230))
im.save(out)
print(out)
