"""G7-1 回归测试：StrategyEvolver 路径遍历防护。

验证用户可控的 strategy_name（源自知识库 title 等）无法通过 ``../``
将策略文件写到 derived/captured 目录之外。
"""
from __future__ import annotations

import os

import pytest

from src.evolution.skill_registry import SkillRegistry
from src.evolution.strategy_evolver import (
    StrategyEvolver,
    _sanitize_skill_name,
)


@pytest.fixture()
def evolver(tmp_path):
    """使用 tmp_path 作为 skills 根目录，避免污染真实 skills 目录。"""
    registry = SkillRegistry(base_path=str(tmp_path))
    return StrategyEvolver(skill_registry=registry, skills_base_path=str(tmp_path))


class TestSanitizeSkillName:
    def test_normal_name_preserved(self):
        assert _sanitize_skill_name("my_strategy") == "my_strategy"

    def test_chinese_preserved(self):
        assert _sanitize_skill_name("均值回归策略") == "均值回归策略"

    def test_path_traversal_collapsed(self):
        # ../ 必须被替换，不能保留为路径分隔
        result = _sanitize_skill_name("evil/../../../payload")
        assert "/" not in result
        assert "\\" not in result
        assert ".." not in result

    def test_backslash_traversal_collapsed(self):
        result = _sanitize_skill_name("evil\\..\\..\\payload")
        assert "\\" not in result
        assert ".." not in result

    def test_empty_falls_back_to_unnamed(self):
        assert _sanitize_skill_name("") == "unnamed"
        assert _sanitize_skill_name("   ") == "unnamed"
        assert _sanitize_skill_name(None) == "unnamed"  # type: ignore[arg-type]

    def test_length_capped(self):
        long_name = "a" * 200
        assert len(_sanitize_skill_name(long_name)) <= 80

    def test_control_chars_replaced(self):
        result = _sanitize_skill_name("a\x00b\nc")
        assert "\x00" not in result
        assert "\n" not in result


class TestSaveSkillPathSafety:
    def test_save_traversal_name_sanitized_not_escaping(self, evolver):
        """_save_skill 对含 ``../`` 的 name：第一道净化已消除路径分隔，
        写入后的文件必须落在目标目录内（不逃逸）。"""
        path = evolver._save_skill("../../escape", "content", "derived")
        base = os.path.abspath(evolver._derived_dir)
        # 规范化后必须仍在 derived 目录内
        assert os.path.commonpath([base, os.path.abspath(path)]) == base
        # 文件名里不应有 .. 或路径分隔符
        assert ".." not in os.path.basename(path)
        assert os.path.exists(path)

    def test_save_refuses_unsanitizable_name(self, evolver, monkeypatch):
        """第二道防御：若净化函数被绕过（返回真正能逃逸的 ../ 开头），_save_skill 必须拒绝。"""
        import src.evolution.strategy_evolver as mod
        # 模拟净化失效：返回以 ../ 开头、能真正逃逸 derived 的名字
        monkeypatch.setattr(mod, "_sanitize_skill_name", lambda name: "../../../escape")
        with pytest.raises(ValueError, match="outside target directory"):
            evolver._save_skill("whatever", "content", "derived")

    def test_save_normal_name_within_dir(self, evolver):
        """正常 name 写入后文件应在目标目录内。"""
        path = evolver._save_skill("normal_strategy", "content", "derived")
        base = os.path.abspath(evolver._derived_dir)
        assert os.path.commonpath([base, os.path.abspath(path)]) == base
        assert os.path.exists(path)

    def test_save_captured_pool_within_dir(self, evolver):
        path = evolver._save_skill("captured_one", "content", "captured")
        base = os.path.abspath(evolver._captured_dir)
        assert os.path.commonpath([base, os.path.abspath(path)]) == base
        assert os.path.exists(path)
