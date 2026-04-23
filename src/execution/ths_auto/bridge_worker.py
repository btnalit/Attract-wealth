#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
32-bit easytrader bridge worker.

This script runs in a 32-bit Python process and proxies easytrader operations
via line-delimited JSON over stdin/stdout.

IMPORTANT: This file must be completely standalone — no src.* imports allowed,
because it runs in a separate Python environment.

Protocol:
  Request:  {"id": N, "method": "...", "params": {...}}\n
  Response: {"id": N, "ok": bool, "result": ..., "error": "..."}\n
"""
from __future__ import annotations

import json
import os
import sys
import traceback


def _respond(stream, msg_id: int, ok: bool, result=None, error: str = ""):
    payload = {"id": msg_id, "ok": ok}
    if result is not None:
        payload["result"] = result
    if error:
        payload["error"] = error
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    stream.write(line)
    stream.flush()


def _safe_to_list(raw):
    """Convert pandas DataFrame or other types to plain list of dicts."""
    if raw is None:
        return []
    try:
        import pandas as pd
        if isinstance(raw, pd.DataFrame):
            return raw.to_dict(orient="records")
    except ImportError:
        pass
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    return [{"raw": str(raw)}]


def _patch_no_foreground(client):
    """Monkey-patch easytrader to prevent all SetForegroundWindow / set_focus calls.

    This keeps xiadan.exe in the background so it never steals focus from the
    user's active window.  Patches applied:

    1. ClientTrader._switch_left_menus  — type_keys('{F5}') with set_foreground=False
    2. ClientTrader._switch_left_menus_by_shortcut — same
    3. PopDialogHandler._set_foreground  — no-op
    4. PopDialogHandler._submit_by_shortcut — type_keys without foreground
    5. grid_strategies._set_foreground (BaseStrategy) — no-op
    6. grid_strategies editor.set_focus in WMCopy._get_clipboard_data — no-op
    """
    import importlib

    # --- 1 & 2: _switch_left_menus / _switch_left_menus_by_shortcut ---
    try:
        ct_mod = importlib.import_module("easytrader.clienttrader")
        ClientTrader = ct_mod.ClientTrader

        _orig_switch = ClientTrader._switch_left_menus

        def _silent_switch(self, path, sleep=0.5):
            self.close_pop_dialog()
            self._get_left_menus_handle().get_item(path).select()
            self._app.top_window().type_keys("{F5}", set_foreground=False)
            self.wait(sleep)

        ClientTrader._switch_left_menus = _silent_switch

        def _silent_switch_by_shortcut(self, shortcut, sleep=0.5):
            self.close_pop_dialog()
            self._app.top_window().type_keys(shortcut, set_foreground=False)
            self.wait(sleep)

        ClientTrader._switch_left_menus_by_shortcut = _silent_switch_by_shortcut
    except Exception:
        pass

    # --- 3 & 4: PopDialogHandler._set_foreground / _submit_by_shortcut ---
    try:
        pdh_mod = importlib.import_module("easytrader.pop_dialog_handler")
        PopDialogHandler = pdh_mod.PopDialogHandler

        @staticmethod
        def _noop_foreground(window):
            pass  # intentionally do nothing — keep background

        PopDialogHandler._set_foreground = _noop_foreground

        def _silent_submit_by_shortcut(self):
            self._app.top_window().type_keys("%Y", set_foreground=False)

        PopDialogHandler._submit_by_shortcut = _silent_submit_by_shortcut
    except Exception:
        pass

    # --- 5: grid_strategies BaseStrategy._set_foreground ---
    try:
        gs_mod = importlib.import_module("easytrader.grid_strategies")

        # Patch the base class _set_foreground used by Copy / Xls strategies
        for cls_name in ("BaseStrategy", "Copy", "Xls", "WMCopy"):
            cls = getattr(gs_mod, cls_name, None)
            if cls is not None and hasattr(cls, "_set_foreground"):
                cls._set_foreground = lambda self, grid=None: None

        # Also neuter the module-level SetForegroundWindow / ShowWindow imports
        # so any stray calls become no-ops
        gs_mod.SetForegroundWindow = lambda hwnd: None
        gs_mod.ShowWindow = lambda hwnd, cmd: None
    except Exception:
        pass

    # --- 6: Neuter win_gui SetForegroundWindow globally ---
    try:
        wg_mod = importlib.import_module("easytrader.utils.win_gui")
        wg_mod.SetForegroundWindow = lambda hwnd: None
        wg_mod.ShowWindow = lambda hwnd, cmd: None
    except Exception:
        pass

    # --- 7: Neuter refresh_strategies imports ---
    try:
        rs_mod = importlib.import_module("easytrader.refresh_strategies")
        if hasattr(rs_mod, "SetForegroundWindow"):
            rs_mod.SetForegroundWindow = lambda hwnd: None
        if hasattr(rs_mod, "ShowWindow"):
            rs_mod.ShowWindow = lambda hwnd, cmd: None
    except Exception:
        pass


def _patch_captcha(engine: str = ""):
    """Patch easytrader captcha recognition to use ddddocr instead of tesseract."""
    engine = (engine or "auto").strip().lower()
    if engine not in ("ddddocr", "auto"):
        return
    try:
        import ddddocr
        ocr = ddddocr.DdddOcr(show_ad=False)
    except ImportError:
        return

    def _captcha_recognize(img_path):
        with open(img_path, "rb") as fp:
            result = ocr.classification(fp.read())
        return str(result or "")

    def _invoke_tesseract_to_recognize(img):
        import io as _io
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        result = ocr.classification(buf.getvalue())
        return str(result or "")

    try:
        import importlib
        captcha_mod = importlib.import_module("easytrader.utils.captcha")
        captcha_mod.captcha_recognize = _captcha_recognize
        captcha_mod.invoke_tesseract_to_recognize = _invoke_tesseract_to_recognize
        try:
            grid_mod = importlib.import_module("easytrader.grid_strategies")
            grid_mod.captcha_recognize = _captcha_recognize
        except Exception:
            pass
    except Exception:
        pass


def main():
    repo_path = os.environ.get("EASYTRADER_REPO_PATH", "").strip()
    if repo_path and os.path.isdir(repo_path) and repo_path not in sys.path:
        sys.path.insert(0, repo_path)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    for candidate in [
        os.path.join(script_dir, "..", "..", "..", "easytrader-master"),
        os.path.join(script_dir, "..", "..", "..", "..", "easytrader-master"),
    ]:
        candidate = os.path.normpath(candidate)
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)

    client = None
    protocol_out = sys.stdout
    sys.stdout = sys.stderr
    inp = sys.stdin

    _respond(protocol_out, 0, True, result={
        "status": "ready",
        "python": sys.executable,
        "bits": 64 if sys.maxsize > 2**32 else 32,
    })

    for line in inp:
        line = line.strip()
        if not line:
            continue

        msg_id = 0
        try:
            req = json.loads(line)
            msg_id = req.get("id", 0)
            method = req.get("method", "")
            params = req.get("params", {})

            if method == "ping":
                _respond(protocol_out, msg_id, True, result="pong")

            elif method == "connect":
                import easytrader
                exe_path = params.get("exe_path", "")
                broker = params.get("broker", "ths")
                grid_strategy = params.get("grid_strategy", "") or os.environ.get("THS_EASYTRADER_GRID_STRATEGY", "")
                captcha_engine = params.get("captcha_engine", "") or os.environ.get("THS_EASYTRADER_CAPTCHA_ENGINE", "")

                _patch_captcha(captcha_engine)

                errors = []
                for candidate_broker in [broker, "ths", "universal_client"]:
                    try:
                        user = easytrader.use(candidate_broker)
                        if grid_strategy:
                            try:
                                import easytrader.grid_strategies as gs
                                strategy_map = {"copy": "Copy", "xls": "Xls", "wmcopy": "WMCopy"}
                                cls_name = strategy_map.get(grid_strategy.lower(), "")
                                if cls_name and hasattr(gs, cls_name):
                                    user.grid_strategy = getattr(gs, cls_name)
                            except Exception:
                                pass
                        user.connect(exe_path=exe_path)
                        _patch_no_foreground(user)
                        client = user
                        _respond(protocol_out, msg_id, True, result={
                            "connected": True,
                            "broker": candidate_broker,
                            "grid_strategy": grid_strategy or "auto",
                        })
                        break
                    except Exception as exc:
                        errors.append(f"{candidate_broker}:{exc}")
                else:
                    _respond(protocol_out, msg_id, False, error=f"connect_failed: {'; '.join(errors)}")

            elif method == "get_balance":
                if client is None:
                    _respond(protocol_out, msg_id, False, error="not_connected")
                else:
                    raw = client.balance
                    # balance returns dict, pass through directly (don't wrap in list)
                    _respond(protocol_out, msg_id, True, result=raw)

            elif method == "get_position":
                if client is None:
                    _respond(protocol_out, msg_id, False, error="not_connected")
                else:
                    raw = client.position
                    _respond(protocol_out, msg_id, True, result=_safe_to_list(raw))

            elif method == "get_today_entrusts":
                if client is None:
                    _respond(protocol_out, msg_id, False, error="not_connected")
                else:
                    raw = client.today_entrusts
                    _respond(protocol_out, msg_id, True, result=_safe_to_list(raw))

            elif method == "get_today_trades":
                if client is None:
                    _respond(protocol_out, msg_id, False, error="not_connected")
                else:
                    raw = client.today_trades
                    _respond(protocol_out, msg_id, True, result=_safe_to_list(raw))

            elif method == "buy":
                if client is None:
                    _respond(protocol_out, msg_id, False, error="not_connected")
                else:
                    ticker = params["ticker"]
                    price = float(params["price"])
                    quantity = int(params["quantity"])
                    raw = client.buy(ticker, price=price, amount=quantity)
                    _respond(protocol_out, msg_id, True, result=raw)

            elif method == "sell":
                if client is None:
                    _respond(protocol_out, msg_id, False, error="not_connected")
                else:
                    ticker = params["ticker"]
                    price = float(params["price"])
                    quantity = int(params["quantity"])
                    raw = client.sell(ticker, price=price, amount=quantity)
                    _respond(protocol_out, msg_id, True, result=raw)

            elif method == "cancel_entrust":
                if client is None:
                    _respond(protocol_out, msg_id, False, error="not_connected")
                else:
                    entrust_no = params.get("entrust_no", "")
                    raw = client.cancel_entrust(entrust_no)
                    _respond(protocol_out, msg_id, True, result=raw)

            elif method == "exit":
                client = None
                _respond(protocol_out, msg_id, True, result="exited")

            elif method == "shutdown":
                client = None
                _respond(protocol_out, msg_id, True, result="shutdown")
                break

            else:
                _respond(protocol_out, msg_id, False, error=f"unknown_method:{method}")

        except json.JSONDecodeError as exc:
            _respond(protocol_out, msg_id, False, error=f"json_decode_error:{exc}")
        except Exception as exc:
            tb = traceback.format_exc()
            _respond(protocol_out, msg_id, False, error=f"{exc}\n{tb}")


if __name__ == "__main__":
    main()
