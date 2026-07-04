#!/usr/bin/env python3
"""Verify BangerForge install — run after git pull if imports fail."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bangerforge.bootstrap import (  # noqa: E402
    REQUIRED_FILES,
    ROOT_DIR,
    format_install_report,
    verify_install,
)


def main() -> int:
    print(f"Project root: {ROOT_DIR}")
    print(f"Python: {sys.executable}")
    print()

    print("Required files:")
    for rel in REQUIRED_FILES:
        path = ROOT_DIR / rel
        status = "OK" if path.is_file() else "MISSING"
        print(f"  [{status}] {rel}")
    print()

    issues = verify_install()
    print(format_install_report(issues))
    print()

    if issues:
        print("Streamlit will not start reliably until the issues above are fixed.")
        return 1

    print("You can start the app with:  streamlit run app.py")
    try:
        import app  # noqa: F401
        print("Import smoke test: import app — OK")
    except Exception as exc:  # noqa: BLE001
        print(f"Import smoke test: import app — FAILED: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())