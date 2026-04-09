# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 同花顺路径解析器 (THS Path Resolver)

通过多级探测策略动态发现同花顺安装路径，彻底消除硬编码。
优先级: 注册表 → 进程探测 → 用户配置 → 常见路径扫描
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 常见同花顺安装目录模板
COMMON_PATHS = [
    r"C:\同花顺软件\同花顺",
    r"D:\同花顺软件\同花顺",
    r"E:\同花顺软件\同花顺",
    r"C:\Program Files (x86)\同花顺软件\同花顺",
    r"C:\Program Files\同花顺软件\同花顺",
    r"D:\ths",
    r"C:\ths",
]

# 注册表探测路径 (THS 可能在以下位置写入安装信息)
REGISTRY_PATHS = [
    # HKCU (当前用户)
    (
        "HKEY_CURRENT_USER",
        r"Software\THS\installpath",
    ),
    (
        "HKEY_CURRENT_USER",
        r"Software\同花顺\installpath",
    ),
    # HKLM (所有用户)
    (
        "HKEY_LOCAL_MACHINE",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\同花顺",
    ),
]


class ThsPathResolver:
    """
    同花顺路径解析器。

    按优先级探测 THS 安装路径，返回标准化的安装信息。
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "ths.json",
        )
        self._cache: Optional[dict[str, Any]] = None

    def resolve(self) -> dict[str, Any]:
        """
        解析同花顺路径。返回标准化的安装信息。

        Returns:
            {
                "found": bool,
                "install_dir": str | None,
                "exe_path": str | None,
                "version": str,
                "source": str,  # "registry" | "process" | "config" | "scan" | "not_found"
                "is_running": bool,
            }
        """
        if self._cache is not None:
            return self._cache

        result: dict[str, Any] = {
            "found": False,
            "install_dir": None,
            "exe_path": None,
            "version": "unknown",
            "source": "not_found",
            "is_running": False,
        }

        # Level 1: 注册表探测
        result = self._probe_registry(result)
        if result["found"]:
            return self._cache_and_return(result)

        # Level 2: 进程探测
        result = self._probe_process(result)
        if result["found"]:
            return self._cache_and_return(result)

        # Level 3: 用户配置文件
        result = self._probe_config(result)
        if result["found"]:
            return self._cache_and_return(result)

        # Level 4: 常见路径扫描
        result = self._probe_common_paths(result)
        if result["found"]:
            return self._cache_and_return(result)

        logger.warning("同花顺路径解析失败: 未在任何位置检测到同花顺安装")
        return self._cache_and_return(result)

    def clear_cache(self) -> None:
        """清除缓存，下次调用时重新探测。"""
        self._cache = None

    # -----------------------------------------------------------------------
    # Probe Methods
    # -----------------------------------------------------------------------

    def _probe_registry(self, result: dict[str, Any]) -> dict[str, Any]:
        """Level 1: 通过注册表探测 THS 安装路径。"""
        if os.name != "nt":
            return result

        try:
            import winreg

            for hive_name, subkey in REGISTRY_PATHS:
                try:
                    hive = getattr(winreg, hive_name, None)
                    if hive is None:
                        continue

                    key = winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ)
                    try:
                        # Try common value names
                        for value_name in ["InstallPath", "Path", "DisplayIcon", ""]:
                            try:
                                value, _ = winreg.QueryValueEx(key, value_name)
                                if value and isinstance(value, str):
                                    install_dir = self._normalize_path(value)
                                    if self._validate_install_dir(install_dir):
                                        result["found"] = True
                                        result["install_dir"] = install_dir
                                        result["exe_path"] = self._find_xiadan(install_dir)
                                        result["source"] = "registry"
                                        logger.info("THS 路径通过注册表发现: %s", install_dir)
                                        return result
                            except (OSError, FileNotFoundError):
                                continue
                    finally:
                        winreg.CloseKey(key)
                except (OSError, FileNotFoundError):
                    continue
        except ImportError:
            pass

        return result

    def _probe_process(self, result: dict[str, Any]) -> dict[str, Any]:
        """Level 2: 通过进程探测正在运行的 THS 路径。"""
        try:
            import psutil

            for proc in psutil.process_iter(["name", "exe", "cmdline"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if "xiadan" in name or "ths" in name or "同花顺" in name:
                        exe_path = proc.info.get("exe") or ""
                        if exe_path and os.path.isfile(exe_path):
                            install_dir = os.path.dirname(exe_path)
                            if self._validate_install_dir(install_dir):
                                result["found"] = True
                                result["install_dir"] = install_dir
                                result["exe_path"] = exe_path
                                result["source"] = "process"
                                result["is_running"] = True
                                logger.info("THS 路径通过进程探测发现: %s (正在运行)", exe_path)
                                return result
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            logger.debug("psutil 未安装，跳过进程探测")

        # Fallback: 使用 tasklist + wmic
        try:
            output = subprocess.check_output(
                ["wmic", "process", "where", "name='xiadan.exe'", "get", "ExecutablePath", "/format:list"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            for line in output.splitlines():
                if line.startswith("ExecutablePath="):
                    exe_path = line.split("=", 1)[1].strip()
                    if exe_path and os.path.isfile(exe_path):
                        install_dir = os.path.dirname(exe_path)
                        if self._validate_install_dir(install_dir):
                            result["found"] = True
                            result["install_dir"] = install_dir
                            result["exe_path"] = exe_path
                            result["source"] = "process"
                            result["is_running"] = True
                            logger.info("THS 路径通过 WMIC 探测发现: %s", exe_path)
                            return result
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return result

    def _probe_config(self, result: dict[str, Any]) -> dict[str, Any]:
        """Level 3: 读取用户配置文件。"""
        config_path = Path(self.config_path)
        if not config_path.is_file():
            return result

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            manual_path = config.get("manual_path") or config.get("install_dir") or config.get("exe_path")
            if manual_path:
                manual_path = self._normalize_path(manual_path)
                if os.path.isdir(manual_path):
                    result["found"] = True
                    result["install_dir"] = manual_path
                    result["exe_path"] = self._find_xiadan(manual_path)
                    result["source"] = "config"
                    logger.info("THS 路径通过配置文件发现: %s", manual_path)
                elif os.path.isfile(manual_path) and "xiadan" in os.path.basename(manual_path).lower():
                    result["found"] = True
                    result["install_dir"] = os.path.dirname(manual_path)
                    result["exe_path"] = manual_path
                    result["source"] = "config"
                    logger.info("THS 路径通过配置文件发现: %s", manual_path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("读取 THS 配置文件失败: %s", exc)

        return result

    def _probe_common_paths(self, result: dict[str, Any]) -> dict[str, Any]:
        """Level 4: 扫描常见安装目录。"""
        # 也检查环境变量
        env_path = os.getenv("THS_INSTALL_DIR") or os.getenv("THS_PATH")
        if env_path:
            env_path = self._normalize_path(env_path)
            if self._validate_install_dir(env_path):
                result["found"] = True
                result["install_dir"] = env_path
                result["exe_path"] = self._find_xiadan(env_path)
                result["source"] = "env"
                logger.info("THS 路径通过环境变量发现: %s", env_path)
                return result

        for path_template in COMMON_PATHS:
            if self._validate_install_dir(path_template):
                result["found"] = True
                result["install_dir"] = path_template
                result["exe_path"] = self._find_xiadan(path_template)
                result["source"] = "scan"
                logger.info("THS 路径通过扫描发现: %s", path_template)
                return result

        return result

    # -----------------------------------------------------------------------
    # Helper Methods
    # -----------------------------------------------------------------------

    def _find_xiadan(self, install_dir: str) -> Optional[str]:
        """在指定目录中寻找 xiadan.exe。"""
        candidates = [
            os.path.join(install_dir, "xiadan.exe"),
            os.path.join(install_dir, "bin", "xiadan.exe"),
            os.path.join(install_dir, "main", "xiadan.exe"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    def _validate_install_dir(self, path: str) -> bool:
        """验证是否为有效的 THS 安装目录。"""
        if not os.path.isdir(path):
            return False
        # 检查是否存在标志性文件
        markers = ["xiadan.exe", "THS.exe", "ths.exe", "hexin.ini"]
        for marker in markers:
            if os.path.isfile(os.path.join(path, marker)):
                return True
            # 检查子目录
            for root, _dirs, files in os.walk(path, topdown=True):
                # 只检查第一层子目录
                if root != path:
                    break
                if marker in files:
                    return True
        return False

    def _normalize_path(self, path: str) -> str:
        """标准化路径字符串。"""
        # 移除可能的引号
        path = path.strip().strip('"').strip("'")
        # 展开环境变量
        path = os.path.expandvars(path)
        # 标准化路径分隔符
        path = path.replace("/", "\\")
        return path

    def _cache_and_return(self, result: dict[str, Any]) -> dict[str, Any]:
        """缓存结果并返回。"""
        self._cache = result
        return result

    def save_config(self, install_dir: str, exe_path: Optional[str] = None) -> None:
        """保存路径到配置文件。"""
        config_path = Path(self.config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        config: dict[str, Any] = {}
        if config_path.is_file():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        config["manual_path"] = self._normalize_path(install_dir)
        if exe_path:
            config["exe_path"] = self._normalize_path(exe_path)
        config["last_updated"] = __import__("time").time()

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info("THS 路径已保存到配置文件: %s", install_dir)
        self.clear_cache()


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_resolver: Optional[ThsPathResolver] = None


def get_ths_path_resolver(config_path: Optional[str] = None) -> ThsPathResolver:
    """获取全局 THS 路径解析器实例。"""
    global _resolver
    if _resolver is None or (_resolver.config_path != (config_path or _resolver.config_path)):
        _resolver = ThsPathResolver(config_path=config_path)
    return _resolver


def resolve_ths_path(config_path: Optional[str] = None) -> dict[str, Any]:
    """快捷函数：解析 THS 路径。"""
    return get_ths_path_resolver(config_path).resolve()


def save_ths_path(install_dir: str, exe_path: Optional[str] = None, config_path: Optional[str] = None) -> None:
    """快捷函数：保存 THS 路径到配置文件。"""
    get_ths_path_resolver(config_path).save_config(install_dir, exe_path)
