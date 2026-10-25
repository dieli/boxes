"""Tests for the Python side of the web app (web/src/py), run with CPython from the repo root:
    uv run --no-project --with affine --with shapely --with qrcode --with typing_extensions \
        --with numpy --with pytest python -m pytest web/tests/py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "web" / "src" / "py")]
