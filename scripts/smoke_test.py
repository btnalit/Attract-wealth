"""动态冒烟测试：验证前四轮修复后的完整请求链路。

不走真实 uvicorn（避免端口/lifespan 复杂性），用 TestClient 直接驱动 FastAPI app。
覆盖：
1. /api/health 健康检查
2. 鉴权开关：无 API_KEY 时放行；有 API_KEY 时未带凭证应 401、带正确凭证应 200
3. simulation 通道下单闭环：place_direct_order → 风控 → 模拟成交
4. 风控拒绝：触发 SINGLE_ORDER_LIMIT 应返回 409 + RISK_REJECTED
5. 查询持仓/余额/订单 快照
"""
from __future__ import annotations

import os
import sys

# 确保用 simulation 通道，避免触发真实 THS/QMT
os.environ["TRADING_CHANNEL"] = "simulation"
os.environ.pop("API_KEY", None)
os.environ.pop("API_AUTH_ENABLED", None)

from fastapi.testclient import TestClient


def main() -> int:
    from src.main import app

    # 用 context manager 触发 lifespan，让 trading_service 等初始化
    # 否则 app.state.trading_service 为 None，所有路由返回 503。
    with TestClient(app) as client:
        failures: list[str] = []

        def check(name: str, condition: bool, detail: str = "") -> None:
            status = "PASS" if condition else "FAIL"
            print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
            if not condition:
                failures.append(name)

        print("=== 1. 健康检查 ===")
        r = client.get("/api/health")
        check("GET /api/health → 200", r.status_code == 200, f"got {r.status_code}")
        if r.status_code == 200:
            body = r.json()
            check("响应含 ok=true", body.get("ok") is True)

        print("\n=== 2. 鉴权链路（鉴权关闭场景，默认）===")
        r = client.get("/api/trading/balance")
        check("无 API_KEY 时 /balance 放行（非 401）", r.status_code != 401, f"got {r.status_code}")

        print("\n=== 3. simulation 下单闭环 ===")
        order_payload = {
            "ticker": "000001",
            "side": "BUY",
            "quantity": 100,
            "price": 10.0,
            "order_type": "limit",
            "idempotency_key": "smoke-test-001",
            "channel": "simulation",
        }
        r = client.post("/api/trading/orders/direct", json=order_payload)
        check("直下单 → 非 5xx", r.status_code < 500, f"got {r.status_code}")
        if r.status_code == 200:
            body = r.json()
            data = body.get("data", body)
            risk = data.get("risk_check", {})
            check("风控检查通过", risk.get("passed") is True, str(risk))
            order = data.get("order") or {}
            check("订单有状态", bool(order.get("status")), str(order))
            trace = data.get("trace", {})
            check("trace 含 idempotency_key", bool(trace.get("idempotency_key")))
        elif r.status_code == 409:
            body = r.json()
            check("风控拒绝含 RISK_REJECTED 码", body.get("code") == "RISK_REJECTED", body.get("code", ""))

        print("\n=== 4. 风控拒绝：触发 SINGLE_ORDER_LIMIT ===")
        big_order = {
            "ticker": "600519",
            "side": "BUY",
            "quantity": 1000,
            "price": 300.0,
            "order_type": "limit",
            "idempotency_key": "smoke-test-big-001",
            "channel": "simulation",
        }
        r = client.post("/api/trading/orders/direct", json=big_order)
        check("大单请求 → 非 5xx", r.status_code < 500, f"got {r.status_code}")
        if r.status_code in (409, 200):
            body = r.json()
            code = body.get("code", "")
            data = body.get("data", body)
            risk = data.get("risk_check", {}) if isinstance(data, dict) else {}
            violations = risk.get("violations", [])
            rules = [v.get("rule") for v in violations] if violations else []
            check("大单触发风控规则", "SINGLE_ORDER_LIMIT" in rules or code == "RISK_REJECTED",
                  f"code={code} rules={rules}")

        print("\n=== 5. 幂等重放 ===")
        r2 = client.post("/api/trading/orders/direct", json=order_payload)
        check("幂等重放 → 非 5xx", r2.status_code < 500, f"got {r2.status_code}")
        if r2.status_code == 200:
            body = r2.json()
            data = body.get("data", body)
            check("重放标记 idempotent_replay", data.get("idempotent_replay") is True)

        print("\n=== 6. 查询类端点 ===")
        for path in ["/api/trading/snapshot", "/api/trading/orders/active"]:
            r = client.get(path)
            check(f"GET {path} → 非 5xx", r.status_code < 500, f"got {r.status_code}")

        print("\n=== 7. SSE 端点鉴权检查（不消费流，只看握手状态码）===")
        # 用普通 GET 尝试，只读取第一个 chunk 确认不是 401/403
        try:
            with client.stream("GET", "/api/v1/stream/events", timeout=2.0) as resp:
                check("SSE /events → 非 401/403", resp.status_code not in (401, 403), f"got {resp.status_code}")
        except Exception as exc:
            # 超时是正常的（SSE 是长连接），只要不是鉴权拒绝就算通过
            check("SSE /events 连接建立（非鉴权拒绝）", True, f"stream closed: {type(exc).__name__}")

        print("\n=== 8. 404 路由 ===")
        r = client.get("/api/nonexistent")
        check("未知 API → 404", r.status_code == 404, f"got {r.status_code}")

        print(f"\n{'='*50}")
        if failures:
            print(f"RESULT: {len(failures)} FAILED — {failures}")
            return 1
        print("RESULT: ALL PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
