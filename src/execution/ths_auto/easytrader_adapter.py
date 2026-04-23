
from __future__ import annotations

import copy
import csv
import ctypes
import io
import importlib
import json
import logging
import os
import re
import struct
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_THS_EXE_PATH = Path(r"D:\同花顺软件\同花顺\xiadan.exe")

_CAPTCHA_LOCK = threading.Lock()
_CAPTCHA_CONFUSABLE_DIGITS_MAP = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "!": "1", "Z": "2", "S": "5", "B": "8", "G": "6"})
_CAPTCHA_RUNTIME_STATS: dict[str, Any] = {
    "engine": "",
    "patched": False,
    "total_requests": 0,
    "successful_requests": 0,
    "empty_results": 0,
    "total_elapsed_ms": 0.0,
    "avg_elapsed_ms": 0.0,
    "last_result": "",
    "last_source": "",
    "last_elapsed_ms": 0.0,
    "last_variant": "",
    "last_error": "",
    "recent": [],
}

_BALANCE_KEYS = {
    "available_cash": ["可用金额", "可用资金", "可用余额", "kyje", "available_cash", "cash", "鍙敤閲戦", "鍙敤璧勯噾", "鍙敤浣欓"],
    "total_assets": ["总资产", "资产总额", "zzc", "total_assets", "鎬昏祫浜?", "璧勪骇鎬婚"],
    "market_value": ["股票市值", "参考市值", "zsz", "market_value", "鑲＄エ甯傚€?", "鍙傝€冨競鍊?"],
}

_ACCOUNT_KEYS = {
    "account_id": ["资金账号", "资金账户", "account_id", "zjzh", "璧勯噾璐﹀彿"],
    "currency": ["币种", "currency", "甯佺"],
    "shareholder_code": ["股东代码", "股东账号", "shareholder_code", "鑲′笢浠ｇ爜"],
}

_POSITION_KEYS = {
    "ticker": ["证券代码", "股票代码", "代码", "zqdm", "code", "ticker", "璇佸埜浠ｇ爜", "鑲＄エ浠ｇ爜"],
    "quantity": ["股票余额", "当前持仓", "持仓数量", "数量", "gpye", "volume", "quantity", "鑲＄エ浣欓", "鎸佷粨鏁伴噺"],
    "available": ["可用余额", "可卖数量", "可用数量", "kyye", "available", "鍙敤浣欓"],
    "avg_cost": ["成本价", "买入均价", "成本", "cbj", "avg_cost", "cost_price", "鎴愭湰浠?"],
    "current_price": ["最新价", "当前价", "市价", "现价", "sj", "price", "current_price", "鏈€鏂颁环", "褰撳墠浠?"],
    "market_value": ["参考市值", "股票市值", "市值", "zsz", "market_value", "鍙傝€冨競鍊?", "鑲＄エ甯傚€?"],
}

_ORDER_KEYS = {
    "order_id": ["合同编号", "委托编号", "委托号", "entrust_no", "order_id", "htbh", "鍚堝悓缂栧彿", "濮旀墭缂栧彿", "濮旀墭鍙?"],
    "ticker": ["证券代码", "股票代码", "代码", "zqdm", "code", "ticker", "璇佸埜浠ｇ爜"],
    "side": ["操作", "买卖标志", "交易方向", "side", "cz", "鎿嶄綔", "涔板崠鏍囧織"],
    "status": ["委托状态", "状态说明", "状态", "status", "bz", "濮旀墭鐘舵€?", "鐘舵€?"],
    "price": ["委托价格", "价格", "wtjg", "price", "濮旀墭浠锋牸"],
    "quantity": ["委托数量", "数量", "wtsl", "qty", "quantity", "濮旀墭鏁伴噺"],
    "filled_quantity": ["成交数量", "已成数量", "cjsl", "filled_qty", "filled_quantity", "鎴愪氦鏁伴噺"],
    "filled_price": ["成交均价", "成交价格", "cjjj", "filled_price", "鎴愪氦鍧囦环", "鎴愪氦浠锋牸"],
}

_TRADE_KEYS = {
    "trade_id": ["成交编号", "成交序号", "trade_id", "cjbh", "鎴愪氦缂栧彿"],
    "order_id": ["合同编号", "委托编号", "委托号", "entrust_no", "order_id", "htbh", "鍚堝悓缂栧彿", "濮旀墭缂栧彿", "濮旀墭鍙?"],
    "ticker": ["证券代码", "股票代码", "代码", "zqdm", "code", "ticker", "璇佸埜浠ｇ爜"],
    "side": ["买卖标志", "操作", "side", "涔板崠鏍囧織", "鎿嶄綔"],
    "price": ["成交价格", "成交均价", "price", "filled_price", "鎴愪氦浠锋牸", "鎴愪氦鍧囦环"],
    "quantity": ["成交数量", "数量", "qty", "quantity", "鎴愪氦鏁伴噺"],
    "trade_time": ["成交时间", "trade_time", "鎴愪氦鏃堕棿"],
    "trade_date": ["成交日期", "trade_date", "鎴愪氦鏃ユ湡"],
}


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_key(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", _to_text(text).lower(), flags=re.UNICODE)


def _pick_first(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    normalized = {_normalize_key(k): v for k, v in row.items()}
    for key in keys:
        value = normalized.get(_normalize_key(key))
        if value not in (None, ""):
            return value
    return None


def _normalize_rows(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        rows: list[dict[str, Any]] = []
        for value in raw.values():
            if isinstance(value, dict):
                rows.append(value)
            elif isinstance(value, list):
                rows.extend(item for item in value if isinstance(item, dict))
        return rows if rows else [raw]
    return []


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    normalized = _normalize_key(text)
    return any(_normalize_key(token) in normalized for token in tokens if token)


def discover_easytrader_repo_candidates(explicit_repo: str = "") -> list[Path]:
    candidates: list[Path] = []
    for raw in [
        explicit_repo,
        os.getenv("EASYTRADER_REPO_PATH", ""),
        str(PROJECT_ROOT.parent / "easytrader-master"),
        str(PROJECT_ROOT / "easytrader-master"),
        str(Path.cwd() / "easytrader-master"),
    ]:
        text = _to_text(raw)
        if not text:
            continue
        path = Path(text).expanduser()
        if path not in candidates:
            candidates.append(path)
    return candidates


def resolve_ths_exe_path(exe_path: str | None = None) -> str:
    default_path = str(DEFAULT_THS_EXE_PATH)
    raw_input = _to_text(exe_path)
    raw = raw_input or _to_text(os.getenv("THS_EXE_PATH", ""))
    if not raw:
        return default_path
    if "閸氬矁濮虫い" in raw or "鍚岃姳椤?" in raw:
        return default_path
    path = Path(raw).expanduser()
    if path.exists():
        return str(path)
    if not raw_input and "xiadan.exe" in raw.lower():
        return default_path
    return str(path)


class _PandasShimDataFrame:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def to_dict(self, orient: str = "records") -> list[dict[str, Any]]:
        if orient != "records":
            raise ValueError("pandas shim only supports orient='records'")
        return list(self._rows)


def _pandas_shim_read_csv(
    source: Any,
    *,
    delimiter: str = "\t",
    dtype: dict[str, Any] | None = None,
    na_filter: bool = False,
    **_: Any,
) -> _PandasShimDataFrame:
    _ = na_filter
    if hasattr(source, "read"):
        content = str(source.read() or "")
    else:
        with open(str(source), encoding="utf-8", errors="replace") as fp:
            content = fp.read()

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    rows: list[dict[str, Any]] = []
    for row in reader:
        item: dict[str, Any] = {}
        for key, value in row.items():
            field = str(key or "")
            text = str(value or "")
            caster = (dtype or {}).get(field)
            if caster is not None:
                try:
                    item[field] = caster(text)
                    continue
                except Exception:  # noqa: BLE001
                    pass
            item[field] = text
        rows.append(item)
    return _PandasShimDataFrame(rows)


def _ensure_pandas_compat() -> dict[str, Any]:
    try:
        importlib.import_module("pandas")
        return {"ok": True, "shim": False, "reason": "native_pandas"}
    except Exception as exc:  # noqa: BLE001
        shim = types.ModuleType("pandas")
        shim.read_csv = _pandas_shim_read_csv  # type: ignore[attr-defined]
        shim.DataFrame = _PandasShimDataFrame  # type: ignore[attr-defined]
        shim.__dict__["__attract_wealth_shim__"] = True
        sys.modules["pandas"] = shim
        return {"ok": True, "shim": True, "reason": "shimmed", "detail": str(exc)}


def load_easytrader_module(explicit_repo: str = "") -> tuple[Any | None, dict[str, Any]]:
    attempts: list[dict[str, str]] = []
    pandas_meta = _ensure_pandas_compat()
    try:
        module = importlib.import_module("easytrader")
        return module, {"ok": True, "source": "pythonpath", "attempts": attempts, "pandas": pandas_meta}
    except Exception as exc:  # noqa: BLE001
        attempts.append({"source": "pythonpath", "error": str(exc)})

    for candidate in discover_easytrader_repo_candidates(explicit_repo):
        if not candidate.exists():
            attempts.append({"source": str(candidate), "error": "path_not_found"})
            continue
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        try:
            module = importlib.import_module("easytrader")
            return module, {"ok": True, "source": str(candidate), "attempts": attempts, "pandas": pandas_meta}
        except Exception as exc:  # noqa: BLE001
            attempts.append({"source": str(candidate), "error": str(exc)})

    return None, {"ok": False, "source": "", "attempts": attempts, "pandas": pandas_meta}


def _normalize_grid_strategy_name(value: str) -> str:
    text = _to_text(value).lower()
    if text in {"auto", "copy", "xls", "wmcopy"}:
        return text
    return "auto"


def _normalize_captcha_engine_name(value: str) -> str:
    text = _to_text(value).lower()
    if text in {"", "auto", "ddddocr"}:
        return "ddddocr"
    return text


def _ensure_repo_on_sys_path(repo_path: str) -> None:
    text = _to_text(repo_path)
    if not text:
        return
    candidate = Path(text).expanduser()
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def _patch_easytrader_grid_strategy(grid_strategy: str) -> tuple[bool, str]:
    strategy = _normalize_grid_strategy_name(grid_strategy)
    if strategy == "auto":
        return True, "auto"

    class_map = {"copy": "Copy", "xls": "Xls", "wmcopy": "WMCopy"}
    try:
        grid_mod = importlib.import_module("easytrader.grid_strategies")
        client_mod = importlib.import_module("easytrader.clienttrader")
        universal_mod = importlib.import_module("easytrader.universal_clienttrader")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    strategy_cls = getattr(grid_mod, class_map.get(strategy, ""), None)
    if strategy_cls is None:
        return False, f"unsupported_grid_strategy:{strategy}"
    try:
        client_mod.ClientTrader.grid_strategy = strategy_cls
        universal_mod.UniversalClientTrader.grid_strategy = strategy_cls
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return True, strategy

def reset_captcha_runtime_stats() -> None:
    with _CAPTCHA_LOCK:
        _CAPTCHA_RUNTIME_STATS.update(
            {
                "engine": "",
                "patched": False,
                "total_requests": 0,
                "successful_requests": 0,
                "empty_results": 0,
                "total_elapsed_ms": 0.0,
                "avg_elapsed_ms": 0.0,
                "last_result": "",
                "last_source": "",
                "last_elapsed_ms": 0.0,
                "last_variant": "",
                "last_error": "",
                "recent": [],
            }
        )


def _mark_captcha_engine_patched(engine: str) -> None:
    with _CAPTCHA_LOCK:
        _CAPTCHA_RUNTIME_STATS["engine"] = engine
        _CAPTCHA_RUNTIME_STATS["patched"] = True


def get_captcha_runtime_stats() -> dict[str, Any]:
    with _CAPTCHA_LOCK:
        return copy.deepcopy(_CAPTCHA_RUNTIME_STATS)


def _captcha_expected_length() -> int:
    return max(0, min(_safe_int(os.getenv("THS_EASYTRADER_CAPTCHA_LEN", "4"), 4), 12))


def _captcha_charset_mode() -> str:
    text = _to_text(os.getenv("THS_EASYTRADER_CAPTCHA_CHARSET", "auto")).lower()
    if text in {"digit", "digits", "numeric"}:
        return "digits"
    if text in {"alnum", "mixed", "auto"}:
        return text
    return "auto"


def _captcha_max_variants() -> int:
    return max(1, min(_safe_int(os.getenv("THS_EASYTRADER_CAPTCHA_MAX_VARIANTS", "6"), 6), 10))


def _captcha_recent_keep() -> int:
    return max(1, min(_safe_int(os.getenv("THS_EASYTRADER_CAPTCHA_RECENT_KEEP", "20"), 20), 200))


def _sanitize_captcha_text(text: str) -> str:
    return "".join(ch for ch in _to_text(text).upper() if ch.isalnum())


def _normalize_captcha_candidates(raw_text: str, *, expected_len: int, charset_mode: str) -> list[str]:
    base = _sanitize_captcha_text(raw_text)
    mapped_digits = "".join(ch for ch in base.translate(_CAPTCHA_CONFUSABLE_DIGITS_MAP) if ch.isdigit())
    candidates = [mapped_digits] if charset_mode == "digits" else [base]
    if charset_mode in {"auto", "mixed"} and mapped_digits and mapped_digits != base:
        candidates.append(mapped_digits)

    normalized: list[str] = []
    for item in candidates:
        text = _to_text(item)
        if expected_len > 0 and len(text) > expected_len:
            text = text[:expected_len]
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _score_captcha_candidate(candidate: str, *, expected_len: int, charset_mode: str) -> float:
    score = float(len(candidate))
    if expected_len > 0:
        score -= abs(len(candidate) - expected_len) * 3.0
        if len(candidate) == expected_len:
            score += 12.0
    digit_count = sum(ch.isdigit() for ch in candidate)
    alpha_count = sum(ch.isalpha() for ch in candidate)
    if charset_mode == "digits":
        score += digit_count * 2.0 - alpha_count * 3.0
    elif charset_mode in {"auto", "mixed"}:
        score += digit_count * 1.0 - alpha_count * 0.4
    return score


def _record_captcha_runtime(*, source: str, result_text: str, elapsed_ms: float, best_variant: str, attempts: list[dict[str, Any]], error: str = "") -> None:
    keep = _captcha_recent_keep()
    with _CAPTCHA_LOCK:
        _CAPTCHA_RUNTIME_STATS["total_requests"] = int(_CAPTCHA_RUNTIME_STATS.get("total_requests", 0)) + 1
        if result_text:
            _CAPTCHA_RUNTIME_STATS["successful_requests"] = int(_CAPTCHA_RUNTIME_STATS.get("successful_requests", 0)) + 1
        else:
            _CAPTCHA_RUNTIME_STATS["empty_results"] = int(_CAPTCHA_RUNTIME_STATS.get("empty_results", 0)) + 1

        total_elapsed = float(_CAPTCHA_RUNTIME_STATS.get("total_elapsed_ms", 0.0)) + float(elapsed_ms)
        total_requests = int(_CAPTCHA_RUNTIME_STATS.get("total_requests", 1))
        _CAPTCHA_RUNTIME_STATS["total_elapsed_ms"] = total_elapsed
        _CAPTCHA_RUNTIME_STATS["avg_elapsed_ms"] = round(total_elapsed / max(total_requests, 1), 3)
        _CAPTCHA_RUNTIME_STATS["last_result"] = result_text
        _CAPTCHA_RUNTIME_STATS["last_source"] = source
        _CAPTCHA_RUNTIME_STATS["last_elapsed_ms"] = round(float(elapsed_ms), 3)
        _CAPTCHA_RUNTIME_STATS["last_variant"] = best_variant
        _CAPTCHA_RUNTIME_STATS["last_error"] = error

        recent = _CAPTCHA_RUNTIME_STATS.get("recent", [])
        if not isinstance(recent, list):
            recent = []
        recent.append(
            {
                "at": round(time.time(), 3),
                "source": source,
                "result": result_text,
                "elapsed_ms": round(float(elapsed_ms), 3),
                "best_variant": best_variant,
                "attempts": attempts[-8:],
                "error": error,
            }
        )
        _CAPTCHA_RUNTIME_STATS["recent"] = recent[-keep:]


def _build_captcha_variants(image_bytes: bytes, io_module: Any) -> list[tuple[str, bytes]]:
    variants: list[tuple[str, bytes]] = [("raw", image_bytes)]
    try:
        from PIL import Image, ImageFilter, ImageOps  # type: ignore
    except Exception:
        return variants

    try:
        image = Image.open(io_module.BytesIO(image_bytes))
        image.load()
    except Exception:
        return variants

    def _add(name: str, img: Any) -> None:
        try:
            buf = io_module.BytesIO()
            img.save(buf, format="PNG")
            payload = buf.getvalue()
            if payload:
                variants.append((name, payload))
        except Exception:
            return

    gray = image.convert("L")
    _add("gray", gray)
    auto = ImageOps.autocontrast(gray)
    _add("autocontrast", auto)
    binary = auto.point(lambda p: 255 if p >= 150 else 0).convert("L")
    _add("binary150", binary)
    _add("binary150_denoise", binary.filter(ImageFilter.MedianFilter(size=3)))
    _add("binary150_x2", binary.resize((max(1, binary.width * 2), max(1, binary.height * 2))))

    seen: set[tuple[int, bytes]] = set()
    deduped: list[tuple[str, bytes]] = []
    for name, payload in variants:
        key = (len(payload), payload[:64])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, payload))
    return deduped[: _captcha_max_variants()]


def _patch_easytrader_captcha_engine(captcha_engine: str) -> tuple[bool, str]:
    engine = _normalize_captcha_engine_name(captcha_engine)
    if engine != "ddddocr":
        return False, f"unsupported_captcha_engine:{engine}"
    try:
        captcha_mod = importlib.import_module("easytrader.utils.captcha")
        ddddocr_mod = importlib.import_module("ddddocr")
        import io
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    ocr = ddddocr_mod.DdddOcr(show_ad=False)
    reset_captcha_runtime_stats()
    _mark_captcha_engine_patched(engine)

    def _recognize_from_bytes(image_bytes: bytes, *, source: str) -> str:
        started = time.perf_counter()
        expected_len = _captcha_expected_length()
        charset_mode = _captcha_charset_mode()
        attempts: list[dict[str, Any]] = []
        best_text = ""
        best_score = -10_000.0
        best_variant = ""

        for variant_name, payload in _build_captcha_variants(image_bytes, io):
            try:
                raw_text = _to_text(ocr.classification(payload))
            except Exception as exc:  # noqa: BLE001
                attempts.append({"variant": variant_name, "error": str(exc)})
                continue

            for candidate in _normalize_captcha_candidates(raw_text, expected_len=expected_len, charset_mode=charset_mode):
                score = _score_captcha_candidate(candidate, expected_len=expected_len, charset_mode=charset_mode)
                attempts.append({"variant": variant_name, "raw": raw_text, "candidate": candidate, "score": round(score, 4)})
                if candidate and score > best_score:
                    best_score = score
                    best_text = candidate
                    best_variant = variant_name

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        _record_captcha_runtime(source=source, result_text=best_text, elapsed_ms=elapsed_ms, best_variant=best_variant, attempts=attempts, error="" if best_text else "empty_result")
        return best_text

    def _captcha_recognize(img_path: str) -> str:
        with open(img_path, "rb") as fp:
            return _recognize_from_bytes(fp.read(), source="captcha_recognize")

    def _invoke_tesseract_to_recognize(img: Any) -> str:
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return _recognize_from_bytes(buffer.getvalue(), source="invoke_tesseract_to_recognize")

    grid_patch_warning = ""
    try:
        captcha_mod.captcha_recognize = _captcha_recognize
        captcha_mod.invoke_tesseract_to_recognize = _invoke_tesseract_to_recognize
        try:
            grid_mod = importlib.import_module("easytrader.grid_strategies")
            grid_mod.captcha_recognize = _captcha_recognize
        except Exception as exc:  # noqa: BLE001
            grid_patch_warning = f"CAPTCHA_GRID_PATCH_FAILED:{exc}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    detail = engine if not grid_patch_warning else f"{engine}|{grid_patch_warning}"
    return True, detail


def apply_easytrader_runtime_patches(*, repo_path: str = "", grid_strategy: str = "", captcha_engine: str = "") -> dict[str, Any]:
    _ensure_repo_on_sys_path(repo_path)
    grid_ok, grid_detail = _patch_easytrader_grid_strategy(grid_strategy)
    captcha_ok, captcha_detail = _patch_easytrader_captcha_engine(captcha_engine)
    return {
        "grid_strategy": {"requested": _normalize_grid_strategy_name(grid_strategy), "ok": bool(grid_ok), "detail": grid_detail},
        "captcha_engine": {
            "requested": _normalize_captcha_engine_name(captcha_engine),
            "ok": bool(captcha_ok),
            "detail": captcha_detail,
            "runtime": get_captcha_runtime_stats(),
        },
    }


def _needs_32bit_bridge(exe_path: str) -> bool:
    """Check if we need a 32-bit bridge (64-bit Python + 32-bit xiadan.exe)."""
    python_bits = _python_bits()
    if python_bits == 32:
        return False
    exe_bits = _detect_pe_bits(exe_path)
    return exe_bits == 32


def _try_bridge_connect(
    *,
    exe_path: str,
    broker: str,
    repo_path: str,
    grid_strategy: str,
    captcha_engine: str,
) -> tuple[Any | None, dict[str, Any]]:
    """Attempt to connect via 32-bit bridge subprocess."""
    from src.execution.ths_auto.bridge_proxy import BridgeProxyClient, discover_python32

    python32 = discover_python32()
    if not python32:
        return None, {
            "ok": False,
            "reason": "python32_not_found",
            "error_code": "THS_PYTHON32_NOT_FOUND",
            "exe_path": exe_path,
            "broker": broker,
            "errors": [
                "当前 Python 为 64 位，xiadan.exe 为 32 位，需要 32 位 Python 作为桥接。"
                "请设置 THS_EASYTRADER_PYTHON32 环境变量指向 32 位 Python 路径，"
                "或安装 32 位 Python (如 Python 3.10-32)。"
            ],
            "load_meta": {"ok": False, "source": "bridge", "python_bits": _python_bits()},
        }

    # Resolve easytrader repo path for the bridge
    easytrader_repo = repo_path or os.getenv("EASYTRADER_REPO_PATH", "").strip()
    if not easytrader_repo:
        for candidate in discover_easytrader_repo_candidates(""):
            if candidate.exists():
                easytrader_repo = str(candidate)
                break

    logger.info(
        "[ths_auto] 检测到架构不匹配 (Python=%dbit, xiadan=32bit)，启动 32 位桥接: %s",
        _python_bits(), python32,
    )

    try:
        proxy = BridgeProxyClient(python32_exe=python32, easytrader_repo=easytrader_repo)
        proxy.connect(
            exe_path=exe_path,
            broker=broker,
            grid_strategy=grid_strategy,
            captcha_engine=captcha_engine,
        )
        return proxy, {
            "ok": True,
            "reason": "connected_via_bridge",
            "error_code": "",
            "exe_path": exe_path,
            "broker": broker,
            "grid_strategy": grid_strategy,
            "captcha_engine": captcha_engine,
            "patches": {},
            "errors": [],
            "load_meta": {
                "ok": True,
                "source": "bridge_32bit",
                "python32": python32,
                "easytrader_repo": easytrader_repo,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return None, {
            "ok": False,
            "reason": "bridge_connect_failed",
            "error_code": "THS_BRIDGE_CONNECT_FAILED",
            "exe_path": exe_path,
            "broker": broker,
            "errors": [str(exc)],
            "load_meta": {
                "ok": False,
                "source": "bridge_32bit",
                "python32": python32,
                "easytrader_repo": easytrader_repo,
            },
        }


def create_easytrader_client(*, exe_path: str, broker: str = "ths", repo_path: str = "", grid_strategy: str = "", captcha_engine: str = "") -> tuple[Any | None, dict[str, Any]]:
    exe = Path(resolve_ths_exe_path(exe_path)).expanduser()
    if not exe.exists():
        return None, {
            "ok": False,
            "reason": "exe_not_found",
            "error_code": "THS_EXE_NOT_FOUND",
            "exe_path": str(exe),
            "broker": broker,
            "errors": [f"exe_not_found:{exe}"],
        }

    requested_grid_strategy = _normalize_grid_strategy_name(grid_strategy or os.getenv("THS_EASYTRADER_GRID_STRATEGY", "auto"))
    requested_captcha_engine = _normalize_captcha_engine_name(captcha_engine or os.getenv("THS_EASYTRADER_CAPTCHA_ENGINE", "auto"))

    # --- 32-bit bridge auto-detection ---
    # If current Python is 64-bit and xiadan.exe is 32-bit, use bridge subprocess
    if _needs_32bit_bridge(str(exe)):
        logger.info("[ths_auto] 64 位 Python 检测到 32 位 xiadan.exe，尝试桥接模式...")
        client, meta = _try_bridge_connect(
            exe_path=str(exe),
            broker=broker,
            repo_path=repo_path,
            grid_strategy=requested_grid_strategy,
            captcha_engine=requested_captcha_engine,
        )
        if client is not None:
            return client, meta
        # Bridge failed — log and fall through to native attempt (may also fail)
        logger.warning("[ths_auto] 桥接模式失败: %s，尝试原生连接...", meta.get("errors", []))

    module, load_meta = load_easytrader_module(repo_path)
    if module is None:
        return None, {
            "ok": False,
            "reason": "easytrader_import_failed",
            "error_code": "EASYTRADER_IMPORT_FAILED",
            "exe_path": str(exe),
            "broker": broker,
            "errors": [row.get("error", "") for row in load_meta.get("attempts", [])],
            "load_meta": load_meta,
        }

    patch_meta = apply_easytrader_runtime_patches(repo_path=repo_path, grid_strategy=requested_grid_strategy, captcha_engine=requested_captcha_engine)

    errors: list[str] = []
    broker_candidates: list[str] = []
    for candidate in [broker, "ths", "universal_client"]:
        text = _to_text(candidate)
        if text and text not in broker_candidates:
            broker_candidates.append(text)

    for broker_name in broker_candidates:
        try:
            user = module.use(broker_name)
            connect_fn = getattr(user, "connect", None)
            if not callable(connect_fn):
                errors.append(f"{broker_name}:missing_connect")
                continue
            connect_fn(exe_path=str(exe))
            return user, {
                "ok": True,
                "reason": "connected",
                "error_code": "",
                "exe_path": str(exe),
                "broker": broker_name,
                "grid_strategy": requested_grid_strategy,
                "captcha_engine": requested_captcha_engine,
                "patches": patch_meta,
                "errors": errors,
                "load_meta": load_meta,
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{broker_name}:{exc}")

    return None, {
        "ok": False,
        "reason": "connect_failed",
        "error_code": "EASYTRADER_CONNECT_FAILED",
        "exe_path": str(exe),
        "broker": broker,
        "grid_strategy": requested_grid_strategy,
        "captcha_engine": requested_captcha_engine,
        "patches": patch_meta,
        "errors": errors,
        "load_meta": load_meta,
    }


def read_client_member(client: Any, member: str) -> Any:
    value = getattr(client, member)
    if callable(value):
        return value()
    return value


def read_client_member_with_retry(client: Any, member: str, *, retries: int | None = None, retry_interval_s: float | None = None) -> tuple[Any, dict[str, Any]]:
    max_retries = retries if retries is not None else _safe_int(os.getenv("THS_EASYTRADER_READ_RETRIES", "2"), 2)
    max_retries = max(1, max_retries)
    interval = retry_interval_s if retry_interval_s is not None else _to_float(os.getenv("THS_EASYTRADER_READ_RETRY_INTERVAL_S", "0.3"))
    interval = max(0.0, interval)

    errors: list[str] = []
    started = time.perf_counter()
    for idx in range(max_retries):
        try:
            payload = read_client_member(client, member)
            return payload, {
                "ok": True,
                "error_code": "",
                "member": member,
                "attempts": idx + 1,
                "errors": errors,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            if idx < max_retries - 1 and interval > 0:
                time.sleep(interval)

    return None, {
        "ok": False,
        "error_code": "THS_READ_MEMBER_FAILED",
        "member": member,
        "attempts": max_retries,
        "errors": errors,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }

def normalize_balance(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    available_cash = _to_float(_pick_first(data, _BALANCE_KEYS["available_cash"]))
    total_assets = _to_float(_pick_first(data, _BALANCE_KEYS["total_assets"]))
    market_value = _to_float(_pick_first(data, _BALANCE_KEYS["market_value"]))
    if total_assets <= 0 and (available_cash > 0 or market_value > 0):
        total_assets = available_cash + market_value
    frozen_cash = max(0.0, total_assets - available_cash - market_value)
    return {"total_assets": total_assets, "available_cash": available_cash, "market_value": market_value, "frozen_cash": frozen_cash, "raw": data}


def extract_account_fields(raw_balance: Any) -> dict[str, Any]:
    data = raw_balance if isinstance(raw_balance, dict) else {}
    account_id = _to_text(_pick_first(data, _ACCOUNT_KEYS["account_id"]))
    currency = _to_text(_pick_first(data, _ACCOUNT_KEYS["currency"]))
    shareholder_value = _pick_first(data, _ACCOUNT_KEYS["shareholder_code"])
    if isinstance(shareholder_value, list):
        shareholder_codes = [_to_text(item) for item in shareholder_value if _to_text(item)]
    else:
        text = _to_text(shareholder_value)
        shareholder_codes = [text] if text else []
    return {"account_id": account_id, "currency": currency, "shareholder_codes": shareholder_codes}


def normalize_positions(raw: Any) -> list[dict[str, Any]]:
    rows = _normalize_rows(raw)
    results: list[dict[str, Any]] = []
    for row in rows:
        ticker = _to_text(_pick_first(row, _POSITION_KEYS["ticker"]))
        if not ticker:
            continue
        quantity = _to_int(_pick_first(row, _POSITION_KEYS["quantity"]))
        available = _to_int(_pick_first(row, _POSITION_KEYS["available"]))
        avg_cost = _to_float(_pick_first(row, _POSITION_KEYS["avg_cost"]))
        market_value = _to_float(_pick_first(row, _POSITION_KEYS["market_value"]))
        current_price = _to_float(_pick_first(row, _POSITION_KEYS["current_price"]))
        if current_price <= 0 and market_value > 0 and quantity > 0:
            current_price = market_value / quantity
        results.append({"ticker": ticker, "quantity": quantity, "available": available, "avg_cost": avg_cost, "current_price": current_price, "market_value": market_value, "raw": row})
    return results


def _map_side(raw: Any) -> str:
    text = _to_text(raw)
    if _contains_any(text, ("sell", "卖出", "鍗栧嚭")):
        return "SELL"
    if _contains_any(text, ("buy", "买入", "涔板叆")):
        return "BUY"
    return "BUY"


def _map_status(raw: Any) -> str:
    text = _to_text(raw)
    if _contains_any(text, ("全部成交", "已成", "filled", "all_traded", "鍏ㄩ儴鎴愪氦")):
        return "filled"
    if _contains_any(text, ("部分成交", "partial", "part_traded", "閮ㄥ垎鎴愪氦")):
        return "partial"
    if _contains_any(text, ("已撤", "撤单", "cancel", "cancelled", "宸叉挙", "鎾ゅ崟")):
        return "cancelled"
    if _contains_any(text, ("拒绝", "废单", "失败", "rejected", "failed", "鎷掔粷", "澶辫触")):
        return "rejected"
    if _contains_any(text, ("已报", "申报", "submitted", "pending", "queued", "宸叉姤")):
        return "submitted"
    return "pending"


def normalize_orders(raw: Any) -> list[dict[str, Any]]:
    rows = _normalize_rows(raw)
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        order_id = _to_text(_pick_first(row, _ORDER_KEYS["order_id"])) or f"easytrader-order-{index}"
        ticker = _to_text(_pick_first(row, _ORDER_KEYS["ticker"]))
        if not ticker:
            continue
        status_raw = _pick_first(row, _ORDER_KEYS["status"])
        results.append(
            {
                "order_id": order_id,
                "ticker": ticker,
                "side": _map_side(_pick_first(row, _ORDER_KEYS["side"])),
                "status": _map_status(status_raw),
                "status_raw": _to_text(status_raw),
                "price": _to_float(_pick_first(row, _ORDER_KEYS["price"])),
                "quantity": _to_int(_pick_first(row, _ORDER_KEYS["quantity"])),
                "filled_quantity": _to_int(_pick_first(row, _ORDER_KEYS["filled_quantity"])),
                "filled_price": _to_float(_pick_first(row, _ORDER_KEYS["filled_price"])),
                "raw": row,
            }
        )
    return results


def normalize_trades(raw: Any) -> list[dict[str, Any]]:
    rows = _normalize_rows(raw)
    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        trade_id = _to_text(_pick_first(row, _TRADE_KEYS["trade_id"])) or f"easytrader-trade-{index}"
        ticker = _to_text(_pick_first(row, _TRADE_KEYS["ticker"]))
        if not ticker:
            continue
        results.append(
            {
                "trade_id": trade_id,
                "order_id": _to_text(_pick_first(row, _TRADE_KEYS["order_id"])),
                "ticker": ticker,
                "side": _map_side(_pick_first(row, _TRADE_KEYS["side"])),
                "price": _to_float(_pick_first(row, _TRADE_KEYS["price"])),
                "quantity": _to_int(_pick_first(row, _TRADE_KEYS["quantity"])),
                "trade_date": _to_text(_pick_first(row, _TRADE_KEYS["trade_date"])),
                "trade_time": _to_text(_pick_first(row, _TRADE_KEYS["trade_time"])),
                "raw": row,
            }
        )
    return results


def extract_broker_order_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ["entrust_no", "order_id", "合同编号", "委托编号", "委托号", "htbh", "鍚堝悓缂栧彿", "濮旀墭缂栧彿", "濮旀墭鍙?"]:
            value = _to_text(payload.get(key))
            if value:
                return value
    text = _to_text(payload)
    if not text:
        return ""
    for marker in ["entrust_no", "order_id", "合同编号", "委托编号", "鍚堝悓缂栧彿", "濮旀墭缂栧彿"]:
        if marker in text and ":" in text:
            return text.split(":", 1)[-1].strip()
    return ""


def summarize_snapshot(balance: dict[str, Any], positions: list[dict[str, Any]], orders: list[dict[str, Any]], trades: list[dict[str, Any]] | None = None, account: dict[str, Any] | None = None) -> dict[str, Any]:
    trade_rows = trades or []
    account_data = account or {}
    tickers = sorted({str(item.get("ticker", "")).strip() for item in positions if str(item.get("ticker", "")).strip()})
    return {
        "has_balance": bool(balance.get("total_assets", 0.0) > 0 or balance.get("available_cash", 0.0) > 0),
        "positions_count": len(positions),
        "orders_count": len(orders),
        "trades_count": len(trade_rows),
        "position_tickers": tickers[:20],
        "available_cash": float(balance.get("available_cash", 0.0)),
        "total_assets": float(balance.get("total_assets", 0.0)),
        "market_value": float(balance.get("market_value", 0.0)),
        "account_id": str(account_data.get("account_id", "") or ""),
        "currency": str(account_data.get("currency", "") or ""),
        "shareholder_codes_count": len(account_data.get("shareholder_codes", []) if isinstance(account_data.get("shareholder_codes", []), list) else []),
    }


def _python_bits() -> int:
    return 64 if sys.maxsize > 2**32 else 32


def _detect_pe_bits(exe_path: str) -> int:
    path = Path(_to_text(exe_path)).expanduser()
    if not path.exists():
        return 0
    try:
        with path.open("rb") as fp:
            if fp.read(2) != b"MZ":
                return 0
            fp.seek(0x3C)
            pe_offset = struct.unpack("<I", fp.read(4))[0]
            fp.seek(pe_offset)
            if fp.read(4) != b"PE\x00\x00":
                return 0
            machine = struct.unpack("<H", fp.read(2))[0]
    except Exception:  # noqa: BLE001
        return 0
    if machine == 0x14C:
        return 32
    if machine == 0x8664:
        return 64
    return 0


def _is_current_process_admin() -> bool | None:
    if os.name != "nt":
        return None
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None


def _find_process_pid(image_name: str) -> tuple[int | None, str]:
    target = _to_text(image_name)
    if not target:
        return None, "empty_process_name"
    try:
        proc = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {target}", "/FO", "CSV", "/NH"], capture_output=True, check=False, text=True, encoding="gbk", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)

    text = (proc.stdout or "").strip()
    text_lower = f"{text}\n{proc.stderr or ''}".lower()
    if "access denied" in text_lower or "拒绝访问" in text_lower:
        return None, "tasklist_access_denied"
    if "no tasks are running" in text_lower:
        return None, ""

    rows = list(csv.reader([line for line in text.splitlines() if line.strip()]))
    for row in rows:
        if len(row) < 2:
            continue
        if row[0].strip().strip('"').lower() != target.lower():
            continue
        try:
            return int(row[1].strip().strip('"')), ""
        except Exception:  # noqa: BLE001
            continue
    if proc.returncode != 0:
        return None, f"tasklist_rc={proc.returncode}"
    return None, ""


def _can_query_process(pid: int) -> tuple[bool, str]:
    if os.name != "nt":
        return True, ""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(0x1000, 0, int(pid))
    if not handle:
        err = ctypes.get_last_error()
        return False, f"open_process_failed:{err}"
    try:
        return True, ""
    finally:
        kernel32.CloseHandle(handle)


def inspect_easytrader_runtime(*, exe_path: str = str(DEFAULT_THS_EXE_PATH), require_32bit_python: bool = True, require_process_access: bool = True) -> dict[str, Any]:
    exe = Path(resolve_ths_exe_path(exe_path)).expanduser()
    process_name = exe.name or "xiadan.exe"
    python_bits = _python_bits()
    exe_bits = _detect_pe_bits(str(exe))
    current_admin = _is_current_process_admin()
    pid, pid_error = _find_process_pid(process_name)

    running_known = pid_error != "tasklist_access_denied"
    running = pid is not None
    access_ok: bool | None = None
    access_error = ""
    if running:
        access_ok, access_error = _can_query_process(pid)

    needs_32bit = exe_bits == 32
    # If 32-bit bridge is available, arch mismatch is not a blocker
    bridge_available = False
    bridge_detect_error = ""
    if needs_32bit and python_bits != 32:
        try:
            from src.execution.ths_auto.bridge_proxy import discover_python32
            bridge_available = discover_python32() is not None
        except Exception as exc:  # noqa: BLE001
            bridge_detect_error = str(exc)
    arch_ok = not (require_32bit_python and needs_32bit and python_bits != 32)
    access_gate_ok = not (require_process_access and running and access_ok is False)
    running_gate_ok = running if running_known else True

    hints: list[str] = []
    errors: list[str] = []
    if not exe.exists():
        hints.append(f"THS_EXE_PATH not found: {exe}")
    if needs_32bit and python_bits != 32:
        if bridge_available:
            hints.append("当前 Python 为 64 位，将通过 32 位桥接子进程连接 easytrader。")
        else:
            hints.append("当前 Python 为 64 位，未找到 32 位 Python 桥接。请设置 THS_EASYTRADER_PYTHON32 环境变量。")
    if not running and running_known:
        hints.append(f"未检测到 {process_name} 进程，请先登录交易客户端。")
    if not running_known:
        hints.append("无法枚举 xiadan 进程（可能是权限限制），将以 easytrader 实际连接结果为准。")
    if pid_error:
        errors.append(pid_error)
    if access_error:
        errors.append(access_error)
    if bridge_detect_error:
        errors.append(f"bridge_detect_failed:{bridge_detect_error}")
    if access_ok is False:
        hints.append("当前进程对 xiadan 进程无查询权限，通常是管理员权限级别不一致导致。")
        if current_admin is False:
            hints.append("请以管理员身份启动来财，或以相同权限级别启动 xiadan。")

    return {
        "ok": bool(exe.exists()) and running_gate_ok and arch_ok and access_gate_ok,
        "exe_path": str(exe),
        "process_name": process_name,
        "process_pid": pid,
        "process_running": running,
        "process_running_known": running_known,
        "process_access_ok": access_ok,
        "process_access_error": access_error,
        "python_bits": python_bits,
        "exe_bits": exe_bits,
        "needs_32bit_python": needs_32bit,
        "bridge_available": bridge_available,
        "current_process_admin": current_admin,
        "require_32bit_python": bool(require_32bit_python),
        "require_process_access": bool(require_process_access),
        "arch_ok": arch_ok,
        "access_gate_ok": access_gate_ok,
        "hints": hints,
        "errors": errors,
    }


def probe_easytrader_readiness(*, exe_path: str = str(DEFAULT_THS_EXE_PATH), broker: str = "ths", repo_path: str = "", grid_strategy: str = "", captcha_engine: str = "", include_orders: bool = False, include_trades: bool = False, close_client: bool = False, runtime_guard: bool = False, require_32bit_python: bool = True, require_process_access: bool = True) -> dict[str, Any]:
    resolved_exe_path = resolve_ths_exe_path(exe_path)
    started = time.time()
    runtime = inspect_easytrader_runtime(exe_path=resolved_exe_path, require_32bit_python=require_32bit_python, require_process_access=require_process_access)
    result: dict[str, Any] = {
        "ok": False,
        "connected": False,
        "exe_path": str(Path(resolved_exe_path).expanduser()),
        "broker": broker,
        "repo_path": repo_path,
        "grid_strategy": _normalize_grid_strategy_name(grid_strategy or os.getenv("THS_EASYTRADER_GRID_STRATEGY", "auto")),
        "captcha_engine": _normalize_captcha_engine_name(captcha_engine or os.getenv("THS_EASYTRADER_CAPTCHA_ENGINE", "auto")),
        "errors": [],
        "meta": {},
        "summary": {},
        "account": {},
        "balance": {},
        "positions": [],
        "orders": [],
        "trades": [],
        "close_client": bool(close_client),
        "runtime_guard": bool(runtime_guard),
        "runtime": runtime,
        "elapsed_ms": 0.0,
    }

    if runtime_guard and not bool(runtime.get("ok", False)):
        result["meta"] = {
            "ok": False,
            "reason": "runtime_guard_failed",
            "error_code": "THS_RUNTIME_GUARD_FAILED",
            "runtime": runtime,
        }
        result["errors"] = list(runtime.get("errors", []))
        result["elapsed_ms"] = round((time.time() - started) * 1000, 3)
        return result

    client, meta = create_easytrader_client(exe_path=resolved_exe_path, broker=broker, repo_path=repo_path, grid_strategy=grid_strategy, captcha_engine=captcha_engine)
    result["meta"] = meta if isinstance(meta, dict) else {}
    if client is None:
        result["errors"] = list((meta or {}).get("errors", [])) if isinstance(meta, dict) else []
        if isinstance(result["meta"], dict):
            result["meta"].setdefault("error_code", "THS_CLIENT_CREATE_FAILED")
        result["meta"]["captcha_stats"] = get_captcha_runtime_stats()
        result["elapsed_ms"] = round((time.time() - started) * 1000, 3)
        return result

    result["connected"] = True
    read_diag: dict[str, Any] = {}
    try:
        read_retries = max(1, _safe_int(os.getenv("THS_EASYTRADER_READ_RETRIES", "2"), 2))
        read_interval = max(0.0, _to_float(os.getenv("THS_EASYTRADER_READ_RETRY_INTERVAL_S", "0.3")))
        read_diag = {"config": {"retries": read_retries, "retry_interval_s": read_interval}}

        raw_balance, balance_diag = read_client_member_with_retry(client, "balance", retries=read_retries, retry_interval_s=read_interval)
        read_diag["balance"] = balance_diag
        if not balance_diag.get("ok", False):
            raise RuntimeError(f"read balance failed: {';'.join(balance_diag.get('errors', []))}")

        raw_positions, positions_diag = read_client_member_with_retry(client, "position", retries=read_retries, retry_interval_s=read_interval)
        read_diag["position"] = positions_diag
        if not positions_diag.get("ok", False):
            raise RuntimeError(f"read position failed: {';'.join(positions_diag.get('errors', []))}")

        raw_orders: Any = []
        if include_orders:
            raw_orders, orders_diag = read_client_member_with_retry(client, "today_entrusts", retries=read_retries, retry_interval_s=read_interval)
            read_diag["today_entrusts"] = orders_diag
            if not orders_diag.get("ok", False):
                result["errors"].append(f"read today_entrusts failed: {';'.join(orders_diag.get('errors', []))}")
                raw_orders = []

        raw_trades: Any = []
        if include_trades:
            raw_trades, trades_diag = read_client_member_with_retry(client, "today_trades", retries=read_retries, retry_interval_s=read_interval)
            read_diag["today_trades"] = trades_diag
            if not trades_diag.get("ok", False):
                result["errors"].append(f"read today_trades failed: {';'.join(trades_diag.get('errors', []))}")
                raw_trades = []

        account = extract_account_fields(raw_balance)
        balance = normalize_balance(raw_balance)
        positions = normalize_positions(raw_positions)
        orders = normalize_orders(raw_orders)
        trades = normalize_trades(raw_trades)

        result["account"] = account
        result["balance"] = balance
        result["positions"] = positions
        result["orders"] = orders
        result["trades"] = trades
        result["summary"] = summarize_snapshot(balance, positions, orders, trades, account)
        result["ok"] = bool(result["summary"].get("has_balance") or result["summary"].get("positions_count", 0) > 0)

        result["meta"]["read_diagnostics"] = read_diag
        result["meta"]["captcha_stats"] = get_captcha_runtime_stats()
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"THS_PROBE_EXCEPTION:{exc}")
        if isinstance(result["meta"], dict):
            if not str(result["meta"].get("error_code", "")).strip():
                result["meta"]["error_code"] = "THS_PROBE_EXCEPTION"
        if read_diag:
            result["meta"]["read_diagnostics"] = read_diag
        result["meta"]["captcha_stats"] = get_captcha_runtime_stats()
    finally:
        if close_client:
            exit_fn = getattr(client, "exit", None)
            if callable(exit_fn):
                try:
                    exit_fn()
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"THS_CLIENT_CLOSE_FAILED:{exc}")
                    if isinstance(result["meta"], dict):
                        if not str(result["meta"].get("error_code", "")).strip():
                            result["meta"]["error_code"] = "THS_CLIENT_CLOSE_FAILED"

    result["elapsed_ms"] = round((time.time() - started) * 1000, 3)
    return result


def compact_probe_for_log(probe: dict[str, Any]) -> str:
    meta = probe.get("meta", {}) if isinstance(probe.get("meta", {}), dict) else {}
    payload = {
        "ok": bool(probe.get("ok", False)),
        "connected": bool(probe.get("connected", False)),
        "summary": probe.get("summary", {}),
        "errors": probe.get("errors", []),
        "meta": {
            "reason": meta.get("reason", ""),
            "broker": meta.get("broker", ""),
            "source": (meta.get("load_meta", {}) if isinstance(meta.get("load_meta", {}), dict) else {}).get("source", ""),
            "captcha_success": (meta.get("captcha_stats", {}) if isinstance(meta.get("captcha_stats", {}), dict) else {}).get("successful_requests", 0),
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
