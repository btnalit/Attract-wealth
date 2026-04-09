from __future__ import annotations

from pathlib import Path

from scripts.dev import cleanup_pytest_temp as module


def test_cleanup_pytest_temp_remove_strays(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pytest-cache-files-abcd").mkdir(parents=True, exist_ok=True)
    (root / ".pytest_cache").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(module, "ROOT_DIR", root)
    monkeypatch.setattr(module, "PYTEST_TMP_ROOT", root / "_pytest_tmp")

    failures = module.cleanup(dry_run=False)
    assert failures == 0
    assert not (root / "pytest-cache-files-abcd").exists()
    assert not (root / ".pytest_cache").exists()
    assert (root / "_pytest_tmp").exists()


def test_cleanup_pytest_temp_dry_run(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pytest-cache-files-abcd").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(module, "ROOT_DIR", root)
    monkeypatch.setattr(module, "PYTEST_TMP_ROOT", root / "_pytest_tmp")

    failures = module.cleanup(dry_run=True)
    assert failures == 0
    assert (root / "pytest-cache-files-abcd").exists()
