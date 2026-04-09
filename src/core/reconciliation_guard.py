# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 对账阻断保护器
剥离自 TradingService，负责在对账失败时阻断下单流程。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


class ReconciliationGuard:
    def __init__(self):
        self.blocked = False
        self.block_reason: dict[str, Any] = {}
        self.blocked_since: float | None = None
        self.last_code: str = ""
        self.ok_streak = 0
        self.auto_unblock_enabled = os.getenv("RECON_AUTO_UNBLOCK_ENABLED", "true").lower() == "true"
        
        try:
            auto_unblock_streak = int(os.getenv("RECON_AUTO_UNBLOCK_OK_STREAK", "2"))
        except ValueError:
            auto_unblock_streak = 2
        self.auto_unblock_required_ok_streak = max(1, auto_unblock_streak)

    def handle_reconciliation_result(self, result: dict[str, Any]):
        """处理对账引擎的结果，更新阻断状态。"""
        code = str(result.get("code", "RECON_UNKNOWN")).upper()
        action = str(result.get("action", "record")).lower()
        issues_count = result.get("issues_count", 0)
        
        self.last_code = code
        
        # Support old-style reports where code/action directly signals a block
        should_block = (
            action == "block" 
            or code in ("RECON_BLOCK", "RECON_ERROR")
            or any(i.get("level") == "CRITICAL" for i in result.get("issues", []))
        )
        
        if code == "RECON_OK" and action != "block":
            self.ok_streak += 1
            if self.blocked and self.auto_unblock_enabled and self.ok_streak >= self.auto_unblock_required_ok_streak:
                self.unblock(reason=f"auto_unblock_streak_{self.ok_streak}", operator="system")
        elif should_block:
            # 重置成功计数
            self.ok_streak = 0
            if not self.blocked:
                self.block(reason=result, operator="system")
        else:
            # Non-blocking non-OK (e.g. RECON_WARN) resets streak
            self.ok_streak = 0

    def block(self, reason: dict[str, Any], operator: str = "system"):
        if not self.blocked:
            self.blocked = True
            self.blocked_since = time.time()
            # Ensure action field for backward compatibility (tests expect it)
            block_reason = reason if isinstance(reason, dict) else {"reason": str(reason)}
            if "action" not in block_reason:
                block_reason["action"] = "block"
            self.block_reason = block_reason
            reason_text = self.block_reason.get("message", str(reason)) if isinstance(self.block_reason, dict) else str(reason)
            logger.error(f"ReconciliationGuard BLOCKED by {operator}: {reason_text}")

    def unblock(self, reason: str = "manual", operator: str = "api"):
        if self.blocked:
            self.blocked = False
            self.blocked_since = None
            # Keep block_reason empty for backward compatibility (tests expect {})
            self.block_reason = {}
            # DON'T reset ok_streak - tests may check it after unblock
            logger.info(f"ReconciliationGuard UNBLOCKED by {operator}: {reason}")

    def get_status(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "blocked_since": self.blocked_since,
            "reason": self.block_reason,
            "last_code": self.last_code,
            "ok_streak": self.ok_streak,
            "auto_unblock_required": self.auto_unblock_required_ok_streak,
        }
