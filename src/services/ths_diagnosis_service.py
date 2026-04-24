"""Service layer for THS host runtime diagnosis aggregation."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.core.ths_host_autostart import (
    DEFAULT_THS_ROOT,
    analyze_host_trigger_chain,
    collect_host_observability_snapshot,
    collect_xiadan_ui_context,
    is_xiadan_running,
    probe_bridge_runtime,
    read_ths_account_context,
)


class THSDiagnosisService:
    """Aggregate THS host runtime diagnosis for API consumption."""

    def __init__(self, ths_root: Path | str | None = None):
        self._default_ths_root = Path(ths_root).expanduser() if ths_root else Path(DEFAULT_THS_ROOT)

    def get_host_diagnosis(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8089,
        timeout_s: float = 1.2,
        ths_root: Path | str | None = None,
    ) -> dict[str, Any]:
        resolved_root = Path(ths_root).expanduser() if ths_root else self._default_ths_root
        resolved_host = str(host or "127.0.0.1").strip() or "127.0.0.1"
        resolved_port = int(port)
        resolved_timeout = float(timeout_s)

        xiadan_running, xiadan_error = is_xiadan_running()
        xiadan_ui_context = collect_xiadan_ui_context()
        runtime_probe = probe_bridge_runtime(host=resolved_host, port=resolved_port, timeout_s=resolved_timeout)
        host_observability = collect_host_observability_snapshot(resolved_root)
        host_trigger_diagnosis = analyze_host_trigger_chain(
            host_observability,
            xiadan_running=xiadan_running,
            runtime_probe=runtime_probe,
            ui_context=xiadan_ui_context,
        )
        account_context = read_ths_account_context(resolved_root)

        hints: list[str] = []
        if xiadan_running is None:
            hints.append("xiadan.exe 进程状态不可读（可能是权限限制），已按 runtime 探针继续判定。")
        elif xiadan_running is False:
            hints.append("未检测到 xiadan.exe 进程，请先登录同花顺交易客户端。")

        if not bool(runtime_probe.get("reachable", False)):
            hints.append("8089 端口不可达，请确认 THS 宿主脚本已加载并启动 bridge。")
        elif not bool(runtime_probe.get("runtime_ok", False)):
            hints.append("端口可达但 runtime 不是 THS 宿主，请检查是否为外部 mock bridge。")

        for hint in host_trigger_diagnosis.get("suggestions", []) if isinstance(host_trigger_diagnosis, dict) else []:
            text = str(hint or "").strip()
            if text:
                hints.append(text)

        deduped_hints: list[str] = []
        for item in hints:
            if item not in deduped_hints:
                deduped_hints.append(item)

        diagnosis_status = str(host_trigger_diagnosis.get("status", "FAIL")).upper()
        ready = diagnosis_status == "PASS"

        return {
            "checked_at": time.time(),
            "status": diagnosis_status,
            "ready": ready,
            "host": resolved_host,
            "port": resolved_port,
            "timeout_s": resolved_timeout,
            "ths_root": str(resolved_root),
            "xiadan_running": xiadan_running,
            "xiadan_process_check": {
                "known": xiadan_running is not None,
                "error": xiadan_error,
            },
            "xiadan_ui_context": xiadan_ui_context,
            "account_context": account_context,
            "runtime_probe": runtime_probe,
            "host_observability": host_observability,
            "host_trigger_diagnosis": host_trigger_diagnosis,
            "hints": deduped_hints,
        }

