# -*- coding: utf-8 -*-
import socket
import threading
import time

_BRIDGE_THREAD = None


def _port_ready(host, port, timeout_s=0.6):
    sock = socket.socket()
    sock.settimeout(timeout_s)
    try:
        sock.connect((host, int(port)))
        return True
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def ensure_laicai_bridge_autostart(host="127.0.0.1", port=8089, wait_s=3.0):
    global _BRIDGE_THREAD

    if _port_ready(host, int(port)):
        return {"status": "already_ready", "ready": True}

    if _BRIDGE_THREAD is not None and _BRIDGE_THREAD.is_alive():
        deadline = time.time() + max(0.5, float(wait_s))
        while time.time() < deadline:
            if _port_ready(host, int(port)):
                return {"status": "already_starting", "ready": True}
            time.sleep(0.2)
        return {"status": "already_starting", "ready": False}

    import laicai_bridge as _bridge

    run_server = getattr(_bridge, "run_server", None)
    if run_server is None:
        return {"status": "missing_run_server", "ready": False}

    _BRIDGE_THREAD = threading.Thread(target=run_server, name="laicai-ths-bridge")
    _BRIDGE_THREAD.daemon = True
    _BRIDGE_THREAD.start()

    deadline = time.time() + max(0.5, float(wait_s))
    while time.time() < deadline:
        if _port_ready(host, int(port)):
            return {"status": "started", "ready": True}
        time.sleep(0.2)
    return {"status": "start_timeout", "ready": False}
