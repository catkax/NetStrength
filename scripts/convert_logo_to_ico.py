"""Convert NetStrength_exe_logo.png to assets/NetStrength.ico."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent

src = PROJECT_ROOT / "NetStrength_exe_logo.png"
dst = PROJECT_ROOT / "assets" / "NetStrength.ico"

if not src.exists():
    raise FileNotFoundError(f"Source PNG not found: {src}")

dst.parent.mkdir(parents=True, exist_ok=True)

img = Image.open(src).convert("RGBA")

# ICO standard sizes
sizes = [256, 128, 64, 48, 32, 16]
resized = [img.resize((s, s), Image.LANCZOS) for s in sizes]

resized[0].save(dst, format="ICO", sizes=[(s, s) for s in sizes], append_images=resized[1:])

print(f"Saved: {dst}")
