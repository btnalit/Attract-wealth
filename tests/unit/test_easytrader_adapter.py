from __future__ import annotations

from src.execution.ths_auto.easytrader_adapter import (
    extract_account_fields,
    extract_broker_order_id,
    inspect_easytrader_runtime,
    normalize_balance,
    normalize_orders,
    normalize_positions,
    normalize_trades,
    probe_easytrader_readiness,
    read_client_member_with_retry,
    resolve_ths_exe_path,
)


def test_normalize_balance_supports_cn_keys():
    payload = {"可用金额": "1000.5", "总资产": "2000.0", "股票市值": "900.0"}
    balance = normalize_balance(payload)
    assert balance["available_cash"] == 1000.5
    assert balance["total_assets"] == 2000.0
    assert balance["market_value"] == 900.0
    assert balance["frozen_cash"] == 99.5


def test_extract_account_fields_from_balance():
    payload = {"资金账号": "A10001", "币种": "CNY", "股东代码": "SH000001"}
    account = extract_account_fields(payload)
    assert account["account_id"] == "A10001"
    assert account["currency"] == "CNY"
    assert account["shareholder_codes"] == ["SH000001"]


def test_normalize_positions_supports_cn_keys():
    rows = [
        {"证券代码": "600000", "股票余额": "200", "可用余额": "100", "成本价": "10.2", "参考市值": "2100"},
    ]
    positions = normalize_positions(rows)
    assert len(positions) == 1
    assert positions[0]["ticker"] == "600000"
    assert positions[0]["quantity"] == 200
    assert positions[0]["available"] == 100
    assert positions[0]["avg_cost"] == 10.2
    assert positions[0]["market_value"] == 2100.0


def test_normalize_orders_supports_cn_keys():
    rows = [
        {"合同编号": "A1", "证券代码": "000001", "操作": "卖出", "委托状态": "部分成交", "委托数量": "100", "成交数量": "20"},
    ]
    orders = normalize_orders(rows)
    assert len(orders) == 1
    assert orders[0]["order_id"] == "A1"
    assert orders[0]["ticker"] == "000001"
    assert orders[0]["side"] == "SELL"
    assert orders[0]["status"] == "partial"
    assert orders[0]["quantity"] == 100
    assert orders[0]["filled_quantity"] == 20


def test_normalize_trades_supports_cn_keys():
    rows = [
        {"成交编号": "T1", "合同编号": "A1", "证券代码": "000001", "买卖标志": "买入", "成交价格": "12.3", "成交数量": "200"},
    ]
    trades = normalize_trades(rows)
    assert len(trades) == 1
    assert trades[0]["trade_id"] == "T1"
    assert trades[0]["order_id"] == "A1"
    assert trades[0]["ticker"] == "000001"
    assert trades[0]["side"] == "BUY"
    assert trades[0]["quantity"] == 200


def test_extract_broker_order_id_from_payload():
    payload = {"entrust_no": "9001"}
    assert extract_broker_order_id(payload) == "9001"


def test_probe_easytrader_readiness_fails_when_exe_missing():
    probe = probe_easytrader_readiness(exe_path=r"D:\__not_exists__\xiadan.exe")
    assert probe["ok"] is False
    assert probe["connected"] is False
    assert probe["meta"]["reason"] == "exe_not_found"


class _ProbeFakeClient:
    def __init__(self):
        self.balance = {"available_cash": 1000, "total_assets": 1000, "market_value": 0, "资金账号": "ACC-1"}
        self.position = []
        self.today_entrusts = []
        self.today_trades = [{"成交编号": "T001", "证券代码": "000001", "成交数量": "100", "成交价格": "11.1"}]
        self.exit_called = 0

    def exit(self):
        self.exit_called += 1


def test_probe_easytrader_readiness_default_does_not_exit_client(monkeypatch):
    fake = _ProbeFakeClient()

    def _fake_create_easytrader_client(**kwargs):
        return fake, {"ok": True, "reason": "connected", "broker": "ths"}

    monkeypatch.setattr(
        "src.execution.ths_auto.easytrader_adapter.create_easytrader_client",
        _fake_create_easytrader_client,
    )
    probe = probe_easytrader_readiness(exe_path=r"D:\dummy\xiadan.exe")
    assert probe["connected"] is True
    assert probe["close_client"] is False
    assert fake.exit_called == 0


def test_probe_easytrader_readiness_collects_trades(monkeypatch):
    fake = _ProbeFakeClient()

    def _fake_create_easytrader_client(**kwargs):
        return fake, {"ok": True, "reason": "connected", "broker": "ths"}

    monkeypatch.setattr(
        "src.execution.ths_auto.easytrader_adapter.create_easytrader_client",
        _fake_create_easytrader_client,
    )
    probe = probe_easytrader_readiness(exe_path=r"D:\dummy\xiadan.exe", include_trades=True)
    assert probe["ok"] is True
    assert probe["summary"]["trades_count"] == 1
    assert probe["account"]["account_id"] == "ACC-1"


def test_probe_easytrader_readiness_close_client_true(monkeypatch):
    fake = _ProbeFakeClient()

    def _fake_create_easytrader_client(**kwargs):
        return fake, {"ok": True, "reason": "connected", "broker": "ths"}

    monkeypatch.setattr(
        "src.execution.ths_auto.easytrader_adapter.create_easytrader_client",
        _fake_create_easytrader_client,
    )
    probe = probe_easytrader_readiness(exe_path=r"D:\dummy\xiadan.exe", close_client=True)
    assert probe["connected"] is True
    assert probe["close_client"] is True
    assert fake.exit_called == 1


def test_inspect_easytrader_runtime_detects_arch_mismatch(monkeypatch):
    monkeypatch.setattr("src.execution.ths_auto.easytrader_adapter._detect_pe_bits", lambda _path: 32)
    monkeypatch.setattr("src.execution.ths_auto.easytrader_adapter._python_bits", lambda: 64)
    monkeypatch.setattr("src.execution.ths_auto.easytrader_adapter._find_process_pid", lambda _name: (1234, ""))
    monkeypatch.setattr("src.execution.ths_auto.easytrader_adapter._can_query_process", lambda _pid: (True, ""))
    monkeypatch.setattr("src.execution.ths_auto.easytrader_adapter._is_current_process_admin", lambda: False)

    runtime = inspect_easytrader_runtime(exe_path=__file__)
    assert runtime["needs_32bit_python"] is True
    assert runtime["arch_ok"] is False
    assert runtime["ok"] is False


def test_probe_easytrader_readiness_runtime_guard_blocks_connection(monkeypatch):
    monkeypatch.setattr(
        "src.execution.ths_auto.easytrader_adapter.inspect_easytrader_runtime",
        lambda **_kwargs: {
            "ok": False,
            "errors": ["runtime_guard_failed"],
            "hints": ["need_32bit"],
        },
    )

    def _should_not_be_called(**kwargs):
        raise AssertionError("create_easytrader_client should not be called when runtime guard fails")

    monkeypatch.setattr(
        "src.execution.ths_auto.easytrader_adapter.create_easytrader_client",
        _should_not_be_called,
    )
    probe = probe_easytrader_readiness(
        exe_path=__file__,
        runtime_guard=True,
    )
    assert probe["connected"] is False
    assert probe["meta"]["reason"] == "runtime_guard_failed"
    assert probe["errors"] == ["runtime_guard_failed"]


def test_resolve_ths_exe_path_fallback_for_mojibake(monkeypatch):
    monkeypatch.setenv("THS_EXE_PATH", r"D:\鍚岃姳椤鸿蒋浠禱鍚岃姳椤篭xiadan.exe")
    resolved = resolve_ths_exe_path("")
    assert resolved.lower().endswith("xiadan.exe")


def test_read_client_member_with_retry_eventual_success(monkeypatch):
    class _FlakyClient:
        def __init__(self):
            self.calls = 0

        @property
        def balance(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("captcha_popup")
            return {"available_cash": 1000, "total_assets": 1000, "market_value": 0}

    monkeypatch.setenv("THS_EASYTRADER_READ_RETRIES", "2")
    monkeypatch.setenv("THS_EASYTRADER_READ_RETRY_INTERVAL_S", "0")
    client = _FlakyClient()
    payload, diag = read_client_member_with_retry(client, "balance")
    assert payload["available_cash"] == 1000
    assert diag["ok"] is True
    assert diag["attempts"] == 2
    assert len(diag["errors"]) == 1


def test_probe_easytrader_readiness_collects_read_diagnostics(monkeypatch):
    class _FlakyProbeClient:
        def __init__(self):
            self.balance_calls = 0
            self.position = []
            self.today_entrusts = []
            self.today_trades = []

        @property
        def balance(self):
            self.balance_calls += 1
            if self.balance_calls == 1:
                raise RuntimeError("transient_balance_read_failure")
            return {"available_cash": 1000, "total_assets": 1000, "market_value": 0, "account_id": "ACC-2"}

    client = _FlakyProbeClient()

    def _fake_create_easytrader_client(**kwargs):
        return client, {"ok": True, "reason": "connected", "broker": "ths"}

    monkeypatch.setenv("THS_EASYTRADER_READ_RETRIES", "2")
    monkeypatch.setenv("THS_EASYTRADER_READ_RETRY_INTERVAL_S", "0")
    monkeypatch.setattr(
        "src.execution.ths_auto.easytrader_adapter.create_easytrader_client",
        _fake_create_easytrader_client,
    )

    probe = probe_easytrader_readiness(exe_path=r"D:\dummy\xiadan.exe")
    assert probe["ok"] is True
    read_diag = probe["meta"]["read_diagnostics"]
    assert read_diag["balance"]["ok"] is True
    assert read_diag["balance"]["attempts"] == 2
    assert len(read_diag["balance"]["errors"]) == 1
