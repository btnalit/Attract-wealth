# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 策略进化器 (Strategy Evolver)

三大进化模式:
  - FIX:      修复语法错误、工具调用参数错误
  - DERIVED:  基于现有策略微调参数或逻辑分支，产生子版本
  - CAPTURED: 从成功交易案例中逆向提取逻辑，生成新 Skill

职责:
  - 接收策略诊断结果或交易复盘报告
  - 触发 LLM 进行代码/规则重构
  - 生成新的 .md 策略文件并写入 derived/ 目录
  - 通过 StrategyStore 创建版本记录
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable

from src.evolution.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Dataclasses
# ---------------------------------------------------------------------------

class EvolutionMode(str, Enum):
    FIX = "fix"
    DERIVED = "derived"
    CAPTURED = "captured"


@dataclass
class DiagnosisReport:
    """策略诊断报告（输入给进化器的错误/不足信息）"""
    strategy_name: str
    strategy_content: str
    mode: EvolutionMode
    issues: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    trade_examples: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def to_prompt_snippet(self) -> str:
        """转化为 LLM 可读的诊断摘要"""
        lines = [
            f"## 策略诊断报告",
            f"策略名称: {self.strategy_name}",
            f"进化模式: {self.mode.value}",
            "",
        ]
        if self.issues:
            lines.append("### 发现的问题")
            for i, issue in enumerate(self.issues, 1):
                lines.append(f"{i}. [{issue.get('severity', 'info')}] {issue.get('title', '')}: {issue.get('description', '')}")
        if self.metrics:
            lines.append("")
            lines.append("### 策略指标")
            for k, v in self.metrics.items():
                lines.append(f"- {k}: {v}")
        if self.trade_examples:
            lines.append("")
            lines.append("### 交易样例")
            for t in self.trade_examples:
                lines.append(f"- {t}")
        if self.context:
            lines.append("")
            lines.append("### 上下文信息")
            for k, v in self.context.items():
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)


@dataclass
class EvolutionResult:
    """进化结果"""
    mode: EvolutionMode
    parent_name: str
    child_name: str
    child_path: str
    content: str
    version_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# LLM Prompts
# ---------------------------------------------------------------------------

FIX_SYSTEM_PROMPT = """你是一个量化策略代码修复专家。
给定一个策略文档（Markdown 格式）和一份诊断报告，你的任务是：
1. 精确定位问题（语法错误、工具调用参数错误、逻辑漏洞）
2. 输出修复后的完整策略文档
3. 在文档末尾附加 `## 修复说明` 段落

规则：
- 保持原有的 YAML frontmatter 结构
- 不得引入未经验证的新逻辑
- 修复说明需简明扼要，列出具体的改动点
"""

DERIVED_SYSTEM_PROMPT = """你是一个量化策略创新专家。
给定一个现有策略和你的优化方向，你的任务是：
1. 基于原策略进行参数微调或逻辑分支扩展
2. 生成一个全新的衍生策略（子版本）
3. 在文档末尾附加 `## 派生说明` 段落

规则：
- 必须在 YAML frontmatter 中标注 parent_strategy 和 evolution_type
- 每次派生只改变 1-2 个核心参数或逻辑，不要全面重写
- 为新策略取一个有意义的派生名
"""

CAPTURED_SYSTEM_PROMPT = """你是一个交易模式逆向工程专家。
给定一组成功的交易案例和策略上下文，你的任务是：
1. 从交易样例中提取共性特征和决策模式
2. 生成一个全新的策略规则文档
3. 在文档末尾附加 `## 捕获来源` 段落

规则：
- 策略文档必须包含完整的 YAML frontmatter
- 描述清楚触发条件、仓位规则、止损止盈逻辑
- 捕获的策略应足够通用，不仅适用于单一标的
"""


# ---------------------------------------------------------------------------
# Strategy Evolver
# ---------------------------------------------------------------------------

class StrategyEvolver:
    """策略进化器 — 实现 FIX / DERIVED / CAPTURED 三大模式"""

    def __init__(
        self,
        skill_registry: SkillRegistry | None = None,
        llm_client: Any | None = None,
        llm_model: str = "gpt-4o",
        skills_base_path: str | None = None,
    ):
        self._registry = skill_registry or SkillRegistry(base_path=skills_base_path)
        self._llm_client = llm_client
        self._llm_model = llm_model
        self._derived_dir = self._ensure_dir(
            os.path.join(self._registry.base_path, "derived")
        )
        self._captured_dir = self._ensure_dir(
            os.path.join(self._registry.base_path, "captured")
        )
        logger.info("StrategyEvolver initialized at %s", self._registry.base_path)

    # -- Public API ------------------------------------------------------------

    def evolve(self, report: DiagnosisReport) -> EvolutionResult:
        """统一入口：根据报告模式自动路由到对应的进化方法"""
        # QA FIX L236: reload registry to ensure latest strategies are in memory
        self._registry.reload_all()
        mode = report.mode
        if mode == EvolutionMode.FIX:
            return self.fix_strategy(report)
        elif mode == EvolutionMode.DERIVED:
            return self.derive_strategy(report)
        elif mode == EvolutionMode.CAPTURED:
            return self.capture_strategy(report)
        else:
            raise ValueError(f"Unknown evolution mode: {mode}")

    def fix_strategy(self, report: DiagnosisReport) -> EvolutionResult:
        """FIX 模式：修复策略文档中的问题"""
        original = self._load_strategy(report.strategy_name)
        prompt = self._build_fix_prompt(original, report)

        fixed_content = self._call_llm(FIX_SYSTEM_PROMPT, prompt)

        child_name = f"{report.strategy_name}_fixed_{self._ts()}"
        child_path = self._save_skill(child_name, fixed_content, "derived")

        return EvolutionResult(
            mode=EvolutionMode.FIX,
            parent_name=report.strategy_name,
            child_name=child_name,
            child_path=child_path,
            content=fixed_content,
            version_hash=self._hash(fixed_content),
            metadata={"issues_fixed": len(report.issues)},
        )

    def derive_strategy(self, report: DiagnosisReport) -> EvolutionResult:
        """DERIVED 模式：从原策略派生出子版本"""
        original = self._load_strategy(report.strategy_name)
        prompt = self._build_derive_prompt(original, report)

        derived_content = self._call_llm(DERIVED_SYSTEM_PROMPT, prompt)

        child_name = f"{report.strategy_name}_v2_{self._ts()}"
        child_path = self._save_skill(child_name, derived_content, "derived")

        return EvolutionResult(
            mode=EvolutionMode.DERIVED,
            parent_name=report.strategy_name,
            child_name=child_name,
            child_path=child_path,
            content=derived_content,
            version_hash=self._hash(derived_content),
            metadata={"parent_version": original[:200] if original else "N/A"},
        )

    def capture_strategy(self, report: DiagnosisReport) -> EvolutionResult:
        """CAPTURED 模式：从成功交易中提取新策略"""
        prompt = self._build_capture_prompt(report)

        captured_content = self._call_llm(CAPTURED_SYSTEM_PROMPT, prompt)

        child_name = f"captured_{report.strategy_name}_{self._ts()}"
        child_path = self._save_skill(child_name, captured_content, "captured")

        return EvolutionResult(
            mode=EvolutionMode.CAPTURED,
            parent_name=report.strategy_name,
            child_name=child_name,
            child_path=child_path,
            content=captured_content,
            version_hash=self._hash(captured_content),
            metadata={"trade_count": len(report.trade_examples)},
        )

    # -- Internal helpers ------------------------------------------------------

    def _load_strategy(self, name: str) -> str:
        """从 human 或 derived 池加载策略原文"""
        # 先查 human 池
        for key, rule in self._registry.human_skills.items():
            if name in key or key in name:
                with open(rule.filepath, "r", encoding="utf-8") as f:
                    return f.read()
        # 再查 derived 池
        for key, rule in self._registry.derived_skills.items():
            if name in key or key in name:
                with open(rule.filepath, "r", encoding="utf-8") as f:
                    return f.read()
        # 如果都没找到，返回策略内容（如果直接提供了）
        raise FileNotFoundError(f"Strategy '{name}' not found in any pool")

    def _build_fix_prompt(self, original: str, report: DiagnosisReport) -> str:
        return (
            "请修复以下策略文档中的问题：\n\n"
            "## 原策略文档\n"
            f"```\n{original}\n```\n\n"
            f"{report.to_prompt_snippet()}\n\n"
            "请输出完整的修复后的策略文档（包含 YAML frontmatter）。"
        )

    def _build_derive_prompt(self, original: str, report: DiagnosisReport) -> str:
        direction = report.context.get("derive_direction", "优化参数和逻辑")
        return (
            "请基于以下策略进行派生进化：\n\n"
            "## 原策略文档\n"
            f"```\n{original}\n```\n\n"
            f"## 派生方向: {direction}\n\n"
            f"{report.to_prompt_snippet()}\n\n"
            "请输出完整的派生策略文档（包含 YAML frontmatter）。"
        )

    def _build_capture_prompt(self, report: DiagnosisReport) -> str:
        trades_text = "\n".join(
            f"- {t}" for t in report.trade_examples
        )
        return (
            "请从以下成功交易案例中提取策略模式：\n\n"
            f"## 策略名称: {report.strategy_name}\n\n"
            f"## 交易样例\n{trades_text}\n\n"
            f"{report.to_prompt_snippet()}\n\n"
            "请输出一个全新的策略规则文档（包含 YAML frontmatter）。"
        )

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用 LLM 获取进化后的策略内容"""
        if self._llm_client is None:
            # Fallback: 返回模拟内容（开发阶段使用）
            logger.warning("LLM client not configured, using fallback template")
            return self._fallback_template(system_prompt, user_prompt)

        try:
            response = self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
            )
            return response.choices[0].message.content
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            raise

    def _save_skill(self, name: str, content: str, pool: str) -> str:
        """保存策略文件到 derived 或 captured 目录"""
        if pool == "captured":
            directory = self._captured_dir
        else:
            directory = self._derived_dir

        filename = f"{name}.md"
        path = os.path.join(directory, filename)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("Saved skill %s → %s", name, path)
        return path

    @staticmethod
    def _ensure_dir(path: str) -> str:
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _ts() -> str:
        return time.strftime("%Y%m%d%H%M%S")

    # -- Fallback templates (dev only) -----------------------------------------

    @staticmethod
    def _fallback_template(system_prompt: str, user_prompt: str) -> str:
        if "FIX" in system_prompt:
            return (
                "---\n"
                "name: placeholder_fixed\n"
                "version: 1.0\n"
                "fix_note: LLM unavailable, placeholder generated\n"
                "---\n\n"
                "## 修复说明\n"
                "- 此为占位策略，LLM 未配置时自动生成\n"
                "- 请配置 LLM client 后重新执行进化\n"
            )
        elif "DERIVED" in system_prompt:
            return (
                "---\n"
                "name: placeholder_derived\n"
                "version: 1.0\n"
                "parent_strategy: unknown\n"
                "evolution_type: derived\n"
                "---\n\n"
                "## 派生说明\n"
                "- 此为占位策略，LLM 未配置时自动生成\n"
            )
        else:
            return (
                "---\n"
                "name: placeholder_captured\n"
                "version: 1.0\n"
                "evolution_type: captured\n"
                "---\n\n"
                "## 捕获来源\n"
                "- 此为占位策略，LLM 未配置时自动生成\n"
            )
