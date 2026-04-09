from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
PYTEST_TMP_ROOT = ROOT_DIR / "_pytest_tmp"
STRAY_PATTERNS = ("pytest-cache-files-*", ".pytest_cache")


def cleanup(dry_run: bool = False) -> int:
    PYTEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    failures = 0
    removed = 0

    for pattern in STRAY_PATTERNS:
        for path in ROOT_DIR.glob(pattern):
            if not path.is_dir():
                continue
            if dry_run:
                print(f"[dry-run] remove {path}")
                continue
            try:
                shutil.rmtree(path)
                removed += 1
                print(f"[removed] {path}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"[skip] {path} :: {exc}")

    if dry_run:
        print(f"[summary] dry-run done, tmp_root={PYTEST_TMP_ROOT}")
    else:
        print(f"[summary] removed={removed} failed={failures} tmp_root={PYTEST_TMP_ROOT}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup pytest temporary artifacts in project root.")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be removed.")
    args = parser.parse_args()
    return 0 if cleanup(dry_run=args.dry_run) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
