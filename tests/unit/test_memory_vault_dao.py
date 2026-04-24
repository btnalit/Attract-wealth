from __future__ import annotations

from src.dao.memory_vault_dao import MemoryVaultDAO


def test_memory_vault_dao_persists_tiers_and_forgotten(tmp_path) -> None:
    dao = MemoryVaultDAO(file_path=tmp_path / "memory_vault_overrides.json")

    empty_state = dao.get_overrides()
    assert empty_state["tiers"] == {}
    assert empty_state["forgotten"] == []

    promote_payload = dao.set_tier(entry_id="m-1", tier="HOT")
    assert promote_payload == {"id": "m-1", "tier": "HOT"}

    state_after_promote = dao.get_overrides()
    assert state_after_promote["tiers"] == {"m-1": "HOT"}
    assert state_after_promote["forgotten"] == []

    forget_payload = dao.forget(entry_id="m-1")
    assert forget_payload == {"id": "m-1", "forgotten": True}

    state_after_forget = dao.get_overrides()
    assert state_after_forget["tiers"] == {}
    assert state_after_forget["forgotten"] == ["m-1"]

    demote_payload = dao.set_tier(entry_id="m-1", tier="COLD")
    assert demote_payload == {"id": "m-1", "tier": "COLD"}

    state_after_restore = dao.get_overrides()
    assert state_after_restore["tiers"] == {"m-1": "COLD"}
    assert state_after_restore["forgotten"] == []


def test_memory_vault_dao_rejects_invalid_input(tmp_path) -> None:
    dao = MemoryVaultDAO(file_path=tmp_path / "memory_vault_overrides.json")

    try:
        dao.set_tier(entry_id="", tier="HOT")
        assert False, "empty entry_id should fail"
    except ValueError as exc:
        assert "entry_id" in str(exc)

    try:
        dao.set_tier(entry_id="m-2", tier="UNKNOWN")
        assert False, "invalid tier should fail"
    except ValueError as exc:
        assert "tier" in str(exc)

    try:
        dao.forget(entry_id="")
        assert False, "empty entry_id should fail"
    except ValueError as exc:
        assert "entry_id" in str(exc)
