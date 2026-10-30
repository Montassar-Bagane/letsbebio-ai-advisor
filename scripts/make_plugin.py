#!/usr/bin/env python3
"""Package the WordPress plugin as reco-engine.zip.

Uses the standard library rather than the `zip` command, which is absent from
minimal WSL and container images.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "wordpress-plugin" / "reco-engine"
OUT = ROOT / "reco-engine.zip"

if not SRC.is_dir():
    sys.exit(f"Plugin source not found: {SRC}")

SKIP_DIRS = {"__pycache__", ".git", "node_modules"}
SKIP_SUFFIX = {".pyc", ".map", ".DS_Store"}

files = []
for p in sorted(SRC.rglob("*")):
    if not p.is_file():
        continue
    if any(part in SKIP_DIRS for part in p.parts):
        continue
    if p.suffix in SKIP_SUFFIX or p.name.startswith("."):
        continue
    files.append(p)

if not files:
    sys.exit(f"No files found under {SRC}")

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for p in files:
        # WordPress expects the plugin folder as the top level of the archive
        z.write(p, p.relative_to(SRC.parent))

size = OUT.stat().st_size / 1024
print(f"Created {OUT.name} ({size:.0f} KB, {len(files)} files)")
for p in files:
    print(f"  {p.relative_to(SRC.parent)}")
print("\nUpload this in WordPress: Plugins -> Add New -> Upload Plugin")
