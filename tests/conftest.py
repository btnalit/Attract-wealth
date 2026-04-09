from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
import warnings

import pytest

from src.core.storage import reset_connections


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYTEST_TMP_ROOT = PROJECT_ROOT / "_pytest_tmp"
FALLBACK_PYTEST_TMP_ROOT = PROJECT_ROOT / "_pytest_tmp_runtime"
ACTIVE_PYTEST_TMP_ROOT = DEFAULT_PYTEST_TMP_ROOT
PYTEST_TEMP_ROOT = ACTIVE_PYTEST_TMP_ROOT / "temp_runtime"
PYTEST_CACHE_DIR = ACTIVE_PYTEST_TMP_ROOT / ".pytest_cache"


def _pick_tmp_root() -> Path:
    override = os.getenv("PYTEST_TMP_ROOT_OVERRIDE", "").strip()
    if override:
        path = Path(override)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return DEFAULT_PYTEST_TMP_ROOT


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _prepare_pytest_tmp_layout() -> None:
    global ACTIVE_PYTEST_TMP_ROOT, PYTEST_TEMP_ROOT, PYTEST_CACHE_DIR
    preferred = _pick_tmp_root()
    if _is_writable_dir(preferred):
        ACTIVE_PYTEST_TMP_ROOT = preferred
    else:
        ACTIVE_PYTEST_TMP_ROOT = FALLBACK_PYTEST_TMP_ROOT
        if not _is_writable_dir(ACTIVE_PYTEST_TMP_ROOT):
            raise RuntimeError(
                f"pytest tmp root is not writable: preferred={preferred}, fallback={ACTIVE_PYTEST_TMP_ROOT}"
            )
        warnings.warn(
            (
                f"pytest tmp root '{preferred}' is not writable, fallback to '{ACTIVE_PYTEST_TMP_ROOT}'. "
                "Please fix ACL for the preferred directory."
            ),
            RuntimeWarning,
            stacklevel=2,
        )
    PYTEST_TEMP_ROOT = ACTIVE_PYTEST_TMP_ROOT / "temp_runtime"
    PYTEST_CACHE_DIR = ACTIVE_PYTEST_TMP_ROOT / ".pytest_cache"
    for path in (ACTIVE_PYTEST_TMP_ROOT, PYTEST_TEMP_ROOT, PYTEST_CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _apply_temp_env() -> None:
    try:
        whoami = subprocess.check_output(["whoami"], text=True).strip()
    except Exception:  # noqa: BLE001
        whoami = ""
    session_user = whoami.split("\\")[-1].strip() if "\\" in whoami else ""
    if session_user:
        os.environ["USERNAME"] = session_user
        os.environ["USER"] = session_user
        os.environ["LOGNAME"] = session_user
    tmp = str(PYTEST_TEMP_ROOT)
    os.environ["TMP"] = tmp
    os.environ["TEMP"] = tmp
    os.environ["TMPDIR"] = tmp
    tempfile.tempdir = tmp


def pytest_configure(config: pytest.Config) -> None:
    from _pytest import pathlib as pytest_pathlib
    from _pytest import tmpdir as pytest_tmpdir

    original_cleanup = pytest_pathlib.cleanup_dead_symlinks

    def _safe_cleanup_dead_symlinks(root: Path) -> None:
        try:
            original_cleanup(root)
        except PermissionError:
            warnings.warn(
                f"skip cleanup_dead_symlinks for inaccessible tmp root: {root}",
                RuntimeWarning,
                stacklevel=2,
            )

    pytest_pathlib.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks
    pytest_tmpdir.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks
    _prepare_pytest_tmp_layout()
    _apply_temp_env()


@pytest.fixture(scope="session", autouse=True)
def _session_tmp_guard() -> None:
    _prepare_pytest_tmp_layout()
    _apply_temp_env()
    yield


@pytest.fixture()
def tmp_path() -> Path:
    base = ACTIVE_PYTEST_TMP_ROOT / "tmp_cases"
    base.mkdir(parents=True, exist_ok=True)
    case = base / uuid.uuid4().hex[:12]
    case.mkdir(parents=True, exist_ok=True)
    try:
        yield case
    finally:
        reset_connections()
        shutil.rmtree(case, ignore_errors=True)
