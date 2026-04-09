from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THS_ROOT = Path(r"D:\同花顺软件\同花顺")
DEFAULT_BRIDGE_SOURCE = PROJECT_ROOT / "src" / "plugins" / "ths" / "laicai_bridge.py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.ths_host_autostart import (  # noqa: E402
    detect_newline,
    inject_autostart_block,
    read_text_with_fallback,
    render_host_bootstrap_script,
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_report_path() -> Path:
    return PROJECT_ROOT / "data" / "smoke" / "reports" / "ths_host_autostart_install_latest.json"


def _backup_path(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / "data" / "ths_host_autostart" / "backup" / stamp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install THS host-side bridge autostart bootstrap files.")
    parser.add_argument("--ths-root", default=str(DEFAULT_THS_ROOT))
    parser.add_argument("--bridge-source", default=str(DEFAULT_BRIDGE_SOURCE))
    parser.add_argument("--bridge-target", default="script/laicai_bridge.py")
    parser.add_argument("--bootstrap-target", default="script/laicai_host_bootstrap.py")
    parser.add_argument("--signals-file", default="script/信号策略/my_signals.py")
    parser.add_argument("--report-output", default=str(_default_report_path()))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    return parser.parse_args()


def _resolve_path(path_like: str, *, root: Path) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path
    return (root / path).resolve()


def _copy_with_backup(src: Path, dst: Path, *, backup_dir: Path | None, dry_run: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "src": str(src),
        "dst": str(dst),
        "exists_before": dst.exists(),
        "backup": "",
        "changed": False,
    }
    if not src.exists():
        row["error"] = "source_not_found"
        return row
    if dst.exists() and backup_dir is not None:
        backup_path = backup_dir / dst.name
        row["backup"] = str(backup_path)
        if not dry_run:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup_path)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    row["changed"] = True
    return row


def _write_text_with_backup(
    dst: Path,
    text: str,
    *,
    backup_dir: Path | None,
    encoding: str = "utf-8",
    dry_run: bool,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "dst": str(dst),
        "backup": "",
        "encoding": encoding,
        "exists_before": dst.exists(),
        "changed": False,
    }
    if dst.exists() and backup_dir is not None:
        backup_path = backup_dir / dst.name
        row["backup"] = str(backup_path)
        if not dry_run:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup_path)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding=encoding)
    row["changed"] = True
    return row


def run_install(args: argparse.Namespace) -> dict[str, Any]:
    started_at = _iso_now()
    ths_root = Path(args.ths_root).expanduser()
    bridge_source = Path(args.bridge_source).expanduser()
    report_output = _resolve_path(args.report_output, root=PROJECT_ROOT)
    report_output.parent.mkdir(parents=True, exist_ok=True)

    bridge_target = _resolve_path(args.bridge_target, root=ths_root)
    bootstrap_target = _resolve_path(args.bootstrap_target, root=ths_root)
    signals_file = _resolve_path(args.signals_file, root=ths_root)

    backup_dir = None if args.no_backup else _backup_path(PROJECT_ROOT)
    report: dict[str, Any] = {
        "report_version": "1.0",
        "started_at": started_at,
        "finished_at": "",
        "dry_run": bool(args.dry_run),
        "inputs": {
            "ths_root": str(ths_root),
            "bridge_source": str(bridge_source),
            "bridge_target": str(bridge_target),
            "bootstrap_target": str(bootstrap_target),
            "signals_file": str(signals_file),
            "backup_dir": str(backup_dir) if backup_dir is not None else "",
        },
        "checks": {
            "ths_root_exists": ths_root.exists(),
            "xiadan_exe_exists": (ths_root / "xiadan.exe").exists(),
            "bridge_source_exists": bridge_source.exists(),
            "signals_file_exists": signals_file.exists(),
        },
        "steps": [],
        "ok": False,
        "error": "",
    }

    if not report["checks"]["ths_root_exists"]:
        report["error"] = "ths_root_not_found"
        report["finished_at"] = _iso_now()
        return report
    if not report["checks"]["bridge_source_exists"]:
        report["error"] = "bridge_source_not_found"
        report["finished_at"] = _iso_now()
        return report
    if not report["checks"]["signals_file_exists"]:
        report["error"] = "signals_file_not_found"
        report["finished_at"] = _iso_now()
        return report

    report["steps"].append(
        {
            "name": "copy_bridge_script",
            **_copy_with_backup(
                bridge_source,
                bridge_target,
                backup_dir=backup_dir,
                dry_run=args.dry_run,
            ),
        }
    )

    bootstrap_text = render_host_bootstrap_script()
    report["steps"].append(
        {
            "name": "write_host_bootstrap",
            **_write_text_with_backup(
                bootstrap_target,
                bootstrap_text,
                backup_dir=backup_dir,
                encoding="utf-8",
                dry_run=args.dry_run,
            ),
        }
    )

    signals_text, encoding = read_text_with_fallback(signals_file)
    patched = inject_autostart_block(signals_text)
    newline = detect_newline(signals_text)
    if not patched.endswith(("\n", "\r")):
        patched = f"{patched}{newline}"
    report["steps"].append(
        {
            "name": "patch_my_signals",
            **_write_text_with_backup(
                signals_file,
                patched,
                backup_dir=backup_dir,
                encoding=encoding,
                dry_run=args.dry_run,
            ),
            "encoding": encoding,
        }
    )

    report["ok"] = True
    report["finished_at"] = _iso_now()
    return report


def main() -> int:
    args = _parse_args()
    report = run_install(args)
    output = _resolve_path(args.report_output, root=PROJECT_ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ths-host-install] report={output}")
    print(f"[ths-host-install] ok={report.get('ok', False)} error={report.get('error', '')}")
    if report.get("ok", False):
        if args.dry_run:
            print("[ths-host-install] dry-run 通过：安装步骤可执行。")
        else:
            print("[ths-host-install] 已完成 bridge 宿主自动拉起安装（laicai_bridge.py + laicai_host_bootstrap.py + my_signals 注入）。")
            print("[ths-host-install] 如下单端已在运行，建议重启一次 xiadan.exe 以加载脚本。")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
