# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 预算恢复保护器
剥离自 TradingService，负责 LLM 成本超支时的自动降级与恢复。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


class BudgetRecoveryGuard:
    def __init__(self):
        self.enabled = os.getenv("TRADE_BUDGET_RECOVERY_ENABLED", "true").lower() == "true"
        self.ratio = max(0.0, min(1.0, _to_float(os.getenv("TRADE_BUDGET_RECOVERY_RATIO", "0.8"))))
        self.cooldown_s = max(0.0, _to_float(os.getenv("TRADE_BUDGET_RECOVERY_COOLDOWN_S", "300")))
        self.action = os.getenv("TRADE_BUDGET_RECOVERY_ACTION", "force_hold").strip().lower()

        self._metrics: dict[str, Any] = {
            "activation_count": 0,
            "release_count": 0,
            "auto_recovery_success_count": 0,
            "recovery_duration_total_s": 0.0,
            "recovery_success_rate": 0.0,
            "avg_recovery_duration_s": 0.0,
            "last_release_duration_s": 0.0,
            "last_recovery_duration_s": 0.0,
            "last_recovery_success_at": None,
            "release_reason_counts": {},
            "active_elapsed_s": 0.0,
        }

        self.state: dict[str, Any] = {
            "active": False,
            "action": self.action,
            "activated_at": None,
            "released_at": None,
            "release_reason": "",
            "last_budget_exceeded_at": None,
            "last_cost_usd": 0.0,
            "budget_usd": 0.0,
            "recovery_threshold_usd": 0.0,
            "cooldown_s": self.cooldown_s,
            "ratio": self.ratio,
            "updated_at": time.time(),
            "metrics": self._metrics,
            "enabled": self.enabled,
        }

    def update_state(self, current_cost: float, budget: float) -> None:
        """根据当前成本和预算更新保护器状态。"""
        if not self.enabled or budget <= 0:
            if self.state["active"]:
                self.state["active"] = False
            return

        threshold = budget * self.ratio
        now = time.time()

        if current_cost >= threshold and not self.state["active"]:
            self.state["active"] = True
            self.state["activated_at"] = now
            self.state["last_budget_exceeded_at"] = now
            self._metrics["activation_count"] += 1
            logger.warning("BudgetRecoveryGuard ACTIVATED: cost %s >= threshold %s", current_cost, threshold)
        elif self.state["active"] and current_cost < threshold:
            activated_at = self.state.get("activated_at", now)
            elapsed = max(0.0, now - activated_at)
            if elapsed >= self.cooldown_s:
                self.state["active"] = False
                self.state["released_at"] = now
                self.state["release_reason"] = "auto_recovered"
                self._metrics["release_count"] += 1
                self._metrics["auto_recovery_success_count"] += 1
                self._metrics["last_release_duration_s"] = round(elapsed, 6)
                self._metrics["last_recovery_duration_s"] = round(elapsed, 6)
                self._metrics["last_recovery_success_at"] = now
                self._metrics["recovery_duration_total_s"] += elapsed
                count = self._metrics["auto_recovery_success_count"]
                self._metrics["recovery_success_rate"] = 1.0 if count > 0 else 0.0
                self._metrics["avg_recovery_duration_s"] = (
                    round(self._metrics["recovery_duration_total_s"] / count, 6) if count > 0 else 0.0
                )
                logger.info("BudgetRecoveryGuard RELEASED: elapsed=%.1fs", elapsed)

        self.state["last_cost_usd"] = current_cost
        self.state["budget_usd"] = budget
        self.state["recovery_threshold_usd"] = threshold
        self.state["updated_at"] = now

        if self.state["active"]:
            self._metrics["active_elapsed_s"] = round(max(0.0, now - self.state["activated_at"]), 6)
        else:
            self._metrics["active_elapsed_s"] = 0.0

    def get_status(self) -> dict[str, Any]:
        return self.state
