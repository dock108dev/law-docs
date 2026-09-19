"""Actual macOS Vision smoke check using synthetic printed text."""

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engines/crash_report/scripts"))
from apple_vision import recognize

im = Image.new("RGB", (1000, 180), "white")
draw = ImageDraw.Draw(im)
font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
draw.text((30, 40), "SYNTHETIC REPORT 12345", font=font, fill="black")
assert "12345" in " ".join(row["text"] for row in recognize(im))
print("Apple Vision synthetic recognition passed")
