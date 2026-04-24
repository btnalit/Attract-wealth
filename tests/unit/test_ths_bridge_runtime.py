from __future__ import annotations

import uuid
from pathlib import Path

from src.core.ths_bridge_runtime import THSBridgeRuntime


class _FakeProc:
    def __init__(self):
        self.pid = 4321
        self._stopped = False

    def poll(self):
        return 0 if self._stopped else None

    def terminate(self):
        self._stopped = True

    def wait(self, timeout=None):  # noqa: ARG002
        self._stopped = True
        return 0

    def kill(self):
        self._stopped = True


def _make_workspace_tmp() -> Path:
    root = Path(__file__).resolve().parents[2] / "_pytest_tmp" / "ths_bridge_runtime"
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / uuid.uuid4().hex[:12]
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir


def test_bridge_runtime_skip_when_channel_not_ths(monkeypatch):
    tmp_path = _make_workspace_tmp()
    monkeypatch.setenv("STARTUP_AUTO_START_THS_BRIDGE", "true")
    runtime = THSBridgeRuntime(project_root=tmp_path)
    state = runtime.start(channel="simulation")
    assert state["requested"] is False
    assert state["started"] is False
    assert state["ready"] is False


def test_bridge_runtime_skip_when_disabled(monkeypatch):
    tmp_path = _make_workspace_tmp()
    monkeypatch.setenv("STARTUP_AUTO_START_THS_BRIDGE", "false")
    runtime = THSBridgeRuntime(project_root=tmp_path)
    state = runtime.start(channel="ths_ipc")
    assert state["enabled"] is False
    assert state["requested"] is False
    assert "STARTUP_AUTO_START_THS_BRIDGE=false" in state["message"]


def test_bridge_runtime_reuse_existing_port(monkeypatch):
    tmp_path = _make_workspace_tmp()
    from src.core import ths_bridge_runtime as module

    monkeypatch.setenv("STARTUP_AUTO_START_THS_BRIDGE", "true")
    monkeypatch.setattr(module, "_wait_port", lambda *args, **kwargs: (True, ""))
    monkeypatch.setattr(
        module,
        "probe_bridge_runtime",
        lambda **kwargs: {  # noqa: ARG005
            "reachable": True,
            "runtime_ok": True,
            "runtime": {"in_ths_api": True, "in_xiadan_api": False},
            "error": "",
        },
    )

    runtime = THSBridgeRuntime(project_root=tmp_path)
    state = runtime.start(channel="ths_ipc")
    assert state["existing"] is True
    assert state["ready"] is True
    assert state["started"] is False


def test_bridge_runtime_script_missing(monkeypatch):
    tmp_path = _make_workspace_tmp()
    from src.core import ths_bridge_runtime as module

    missing_script = tmp_path / "no_bridge.py"
    monkeypatch.setenv("STARTUP_AUTO_START_THS_BRIDGE", "true")
    monkeypatch.setenv("THS_BRIDGE_SCRIPT", str(missing_script))
    monkeypatch.setattr(module, "_wait_port", lambda *args, **kwargs: (False, "unreachable"))

    runtime = THSBridgeRuntime(project_root=tmp_path)
    state = runtime.start(channel="ths_ipc")
    assert state["started"] is False
    assert state["ready"] is False
    assert "bridge script not found" in state["message"]


def test_bridge_runtime_start_and_stop(monkeypatch):
    tmp_path = _make_workspace_tmp()
    from src.core import ths_bridge_runtime as module

    bridge_script = tmp_path / "bridge.py"
    bridge_script.write_text("print('bridge')", encoding="utf-8")

    calls = {"count": 0}

    def _wait_port(*args, **kwargs):  # noqa: ARG001
        calls["count"] += 1
        if calls["count"] == 1:
            return False, "not-ready-yet"
        return True, ""

    monkeypatch.setenv("STARTUP_AUTO_START_THS_BRIDGE", "true")
    monkeypatch.setenv("THS_BRIDGE_SCRIPT", str(bridge_script))
    monkeypatch.setattr(module, "_wait_port", _wait_port)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: _FakeProc())  # noqa: ARG005
    monkeypatch.setattr(
        module,
        "probe_bridge_runtime",
        lambda **kwargs: {  # noqa: ARG005
            "reachable": True,
            "runtime_ok": True,
            "runtime": {"in_ths_api": True, "in_xiadan_api": False},
            "error": "",
        },
    )

    runtime = THSBridgeRuntime(project_root=tmp_path)
    started = runtime.start(channel="ths_ipc")
    assert started["started"] is True
    assert started["owned"] is True
    assert started["ready"] is True
    assert started["pid"] == 4321

    stopped = runtime.stop(reason="unit_test")
    assert stopped["stopped"] is True
    assert stopped["shutdown_reason"] == "unit_test"


def test_bridge_runtime_start_with_command(monkeypatch):
    tmp_path = _make_workspace_tmp()
    from src.core import ths_bridge_runtime as module

    calls = {"count": 0}

    def _wait_port(*args, **kwargs):  # noqa: ARG001
        calls["count"] += 1
        if calls["count"] == 1:
            return False, "not-ready-yet"
        return True, ""

    monkeypatch.setenv("STARTUP_AUTO_START_THS_BRIDGE", "true")
    monkeypatch.setenv("THS_BRIDGE_START_COMMAND", "echo bridge-start")
    monkeypatch.setattr(module, "_wait_port", _wait_port)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: _FakeProc())  # noqa: ARG005
    monkeypatch.setattr(
        module,
        "probe_bridge_runtime",
        lambda **kwargs: {  # noqa: ARG005
            "reachable": True,
            "runtime_ok": True,
            "runtime": {"in_ths_api": True, "in_xiadan_api": False},
            "error": "",
        },
    )

    runtime = THSBridgeRuntime(project_root=tmp_path)
    state = runtime.start(channel="ths_ipc")
    assert state["started"] is True
    assert state["ready"] is True
    assert state["start_command"] == "echo bridge-start"


def test_bridge_runtime_marks_not_ready_when_runtime_not_host(monkeypatch):
    tmp_path = _make_workspace_tmp()
    from src.core import ths_bridge_runtime as module

    bridge_script = tmp_path / "bridge.py"
    bridge_script.write_text("print('bridge')", encoding="utf-8")

    calls = {"count": 0}

    def _wait_port(*args, **kwargs):  # noqa: ARG001
        calls["count"] += 1
        if calls["count"] == 1:
            return False, "not-ready-yet"
        return True, ""

    monkeypatch.setenv("STARTUP_AUTO_START_THS_BRIDGE", "true")
    monkeypatch.setenv("THS_BRIDGE_SCRIPT", str(bridge_script))
    monkeypatch.setenv("STARTUP_REQUIRE_THS_HOST_RUNTIME", "true")
    monkeypatch.setattr(module, "_wait_port", _wait_port)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: _FakeProc())  # noqa: ARG005
    monkeypatch.setattr(
        module,
        "probe_bridge_runtime",
        lambda **kwargs: {  # noqa: ARG005
            "reachable": True,
            "runtime_ok": False,
            "runtime": {"in_ths_api": False, "in_xiadan_api": False},
            "error": "",
        },
    )

    runtime = THSBridgeRuntime(project_root=tmp_path)
    state = runtime.start(channel="ths_ipc")
    assert state["started"] is True
    assert state["ready"] is False
    assert state["stopped"] is True
    assert state["shutdown_reason"] == "runtime_not_host"
    assert "runtime is not THS host" in state["message"]
