import ast
from pathlib import Path

from src.core.ths_host_autostart import render_host_bootstrap_script


def _assert_py35_compatible_syntax(source: str) -> None:
    tree = ast.parse(source)
    ast.parse(source, feature_version=(3, 5))
    assert all(not isinstance(node, ast.AnnAssign) for node in ast.walk(tree))
    assert all(not isinstance(node, ast.JoinedStr) for node in ast.walk(tree))


def test_laicai_bridge_source_is_py35_compatible():
    bridge_path = Path(__file__).resolve().parents[2] / "src" / "plugins" / "ths" / "laicai_bridge.py"
    source = bridge_path.read_text(encoding="utf-8-sig")

    assert "from __future__ import annotations" not in source
    _assert_py35_compatible_syntax(source)


def test_rendered_host_bootstrap_is_py35_compatible():
    source = render_host_bootstrap_script()

    assert "from __future__ import annotations" not in source
    _assert_py35_compatible_syntax(source)
