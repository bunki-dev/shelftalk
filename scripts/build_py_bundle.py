"""Build the in-browser bundle: web/public/data/shelftalk.zip.

Holds the Python package (without server-only modules and the generator) plus the
generated SQLite warehouse, so the browser needs no numpy and no server.
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "shelftalk"
OUT = ROOT / "web" / "public" / "data" / "shelftalk.zip"
LEAVE_OUT = {"cli.py", "mcp_server.py", "generate.py"}

sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    from shelftalk.generate import build

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "shelftalk.db"
        build(db)
        files = 0
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for path in sorted(SRC.rglob("*")):
                if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.parent == SRC and path.name in LEAVE_OUT:
                    continue
                zf.write(path, Path("shelftalk") / path.relative_to(SRC))
                files += 1
            zf.write(db, "shelftalk.db")
    print(f"Wrote {OUT.relative_to(ROOT)} ({files} package files + warehouse, {OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
