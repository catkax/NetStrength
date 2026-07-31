"""Convert a NetStrength PNG asset into assets/NetStrength.ico."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def _find_source_png(project_root: Path) -> Path:
    candidates = [
        project_root / "assets" / "NetStrength_icon.png",
        project_root / "assets" / "netstrength_icon.png",
        project_root / "assets" / "NetStrength_logo.png",
        project_root / "assets" / "netstrength_logo.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "No source PNG icon found. Expected one of: "
        + ", ".join(str(path) for path in candidates)
    )


src = _find_source_png(PROJECT_ROOT)
dst = PROJECT_ROOT / "assets" / "NetStrength.ico"

dst.parent.mkdir(parents=True, exist_ok=True)

img = Image.open(src).convert("RGBA")

# ICO standard sizes
sizes = [256, 128, 64, 48, 32, 16]
resized = [img.resize((s, s), Image.LANCZOS) for s in sizes]

resized[0].save(dst, format="ICO", sizes=[(s, s) for s in sizes], append_images=resized[1:])

print(f"Source: {src}")
print(f"Saved: {dst}")
