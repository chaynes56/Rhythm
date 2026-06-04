#!/usr/bin/env python3
"""Regenerate app/data_samples.py from app/assets/{vs}/*.wav.

Run from the project root:
    python dev/embed_samples.py
"""
import base64
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "app" / "assets"
OUT = Path(__file__).parent.parent / "app" / "data_samples.py"

voicing_sets = sorted(d.name for d in ASSETS.iterdir() if d.is_dir())

lines = [
    "# Embedded WAV samples for cloud deployments where subdirectory binary files",
    "# are not deployed. Regenerate with: python dev/embed_samples.py",
    "SAMPLES: dict[str, dict[str, str]] = {",
]
for vs in voicing_sets:
    lines.append(f"    {vs!r}: {{")
    for wav_path in sorted((ASSETS / vs).glob("*.wav")):
        encoded = base64.b64encode(wav_path.read_bytes()).decode("ascii")
        lines.append(f"        {wav_path.stem!r}: (")
        for i in range(0, len(encoded), 88):
            lines.append(f"            {encoded[i:i + 88]!r}")
        lines.append("        ),")
    lines.append("    },")
lines.append("}")

OUT.write_text("\n".join(lines) + "\n")
print(f"Written {OUT} ({OUT.stat().st_size:,} bytes, {len(voicing_sets)} voicing sets)")
