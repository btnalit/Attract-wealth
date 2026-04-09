from __future__ import annotations

import os

from src.core.dataflow_profiles import (
    apply_dataflow_env,
    current_dataflow_env_snapshot,
    diff_profile_against_current,
    list_dataflow_profiles,
    resolve_dataflow_profile,
)


def _capture_env(keys: list[str]) -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in keys}


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
            continue
        os.environ[key] = value


def test_profile_catalog_and_resolve():
    profiles = list_dataflow_profiles()
    assert "dev_default" in profiles
    assert "sim_default" in profiles
    assert "prod_live" in profiles
    assert "ths_live_safe" in profiles
    assert "ths_paper_default" in profiles
    assert profiles["ths_live_safe"]["version"]

    dev_map = resolve_dataflow_profile("dev")
    assert dev_map is not None
    assert dev_map["DATA_PROVIDER_RATE_LIMIT_PER_MINUTE"] == "200"

    env_map = resolve_dataflow_profile("ths_live_safe")
    assert env_map is not None
    assert env_map["DATA_PROVIDER_RATE_LIMIT_PER_MINUTE"] == "90"


def test_apply_env_and_diff_roundtrip():
    profile = resolve_dataflow_profile("ths_paper_default")
    assert profile is not None
    keys = list(profile.keys())
    backup = _capture_env(keys)

    try:
        applied = apply_dataflow_env(profile)
        assert applied["DATA_PROVIDER_BACKOFF_RETRIES"] == "2"
        snapshot = current_dataflow_env_snapshot()
        assert snapshot["DATA_PROVIDER_BACKOFF_RETRIES"] == "2"

        diff = diff_profile_against_current("ths_paper_default")
        assert diff == {}
    finally:
        _restore_env(backup)
