# -*- coding: utf-8 -*-
"""CaiShen MCP Server 集成测试。
需要通达信客户端已打开并登录，PostgreSQL 已运行。
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caishen_mcp.ctx_helper import safe_result, check_tq_alive
from caishen_mcp.server import _CFG, _DB_URL, _CONSOLE


def test_tq_alive():
    """验证 TQ 连接存活"""
    assert check_tq_alive(), "TQ 连接失败，请确认通达信客户端已打开"
    print("PASS: TQ 连接正常")


def test_safe_result():
    """验证统一输出格式"""
    ok = safe_result("ok", data={"a": 1}, summary="test")
    assert json.loads(ok) == {"status": "ok", "data": {"a": 1}, "summary": "test"}

    err = safe_result("error", message="test error")
    assert json.loads(err) == {"status": "error", "message": "test error"}

    partial = safe_result("partial", succeeded=3, failed=1, errors=["bad"])
    assert json.loads(partial) == {"status": "partial", "succeeded": 3, "failed": 1, "errors": ["bad"]}
    print("PASS: safe_result 输出格式正确")


def test_formula_list_all():
    """验证 formula_list_all tool"""
    from caishen_mcp.tools.formula_tools import formula_list_all
    result = json.loads(formula_list_all("zb"))
    assert result["status"] == "ok", f"formula_list_all 失败: {result}"
    assert result["total"] > 0, "应至少有一个技术指标公式"
    print(f"PASS: formula_list_all — {result['summary']}")


def test_get_stock_list():
    """验证 get_stock_list tool"""
    from caishen_mcp.tools.data_tools import get_stock_list
    result = json.loads(get_stock_list(""))
    assert result["status"] == "ok", f"get_stock_list 失败: {result}"
    assert result["total"] > 0, "应至少有一只股票"
    print(f"PASS: get_stock_list — {result['summary']}")


def test_get_trading_dates():
    """验证 get_trading_dates tool"""
    from caishen_mcp.tools.data_tools import get_trading_dates
    result = json.loads(get_trading_dates("SH", 5))
    assert result["status"] == "ok", f"get_trading_dates 失败: {result}"
    assert result["total"] >= 1, "应至少有一个交易日"
    print(f"PASS: get_trading_dates — {result['summary']}")


def test_get_match_stkinfo():
    """验证 get_match_stkinfo tool"""
    from caishen_mcp.tools.data_tools import get_match_stkinfo
    result = json.loads(get_match_stkinfo("茅台"))
    assert result["status"] == "ok", f"get_match_stkinfo 失败: {result}"
    print(f"PASS: get_match_stkinfo — {result['summary']}")


def test_get_sector_list():
    """验证 get_sector_list tool"""
    from caishen_mcp.tools.sector_tools import get_sector_list
    result = json.loads(get_sector_list())
    assert result["status"] == "ok", f"get_sector_list 失败: {result}"
    assert result["total"] > 0, "应至少有一个板块"
    print(f"PASS: get_sector_list — {result['summary']}")


def test_formula():
    """验证 formula tool — 单股票 MACD 计算"""
    from caishen_mcp.tools.formula_tools import formula
    result = json.loads(formula(
        formula_type="zb", name="MACD", stocks=["603337.SH"],
        args=["12", "26", "9"], count=10,
    ))
    assert result["status"] == "ok", f"formula 失败: {result}"
    print(f"PASS: formula MACD — {result['summary']}")


def test_error_handling():
    """验证错误处理 — 不存在的公式类型"""
    from caishen_mcp.tools.formula_tools import formula_list_all
    result = json.loads(formula_list_all("invalid_type"))
    assert result["status"] == "error", f"应返回 error 状态: {result}"
    print(f"PASS: 错误处理正常 — {result['message']}")


if __name__ == "__main__":
    print("=" * 60)
    print("CaiShen MCP Server 集成测试")
    print("=" * 60)

    tests = [
        ("TQ 连接正常", test_tq_alive),
        ("safe_result 输出格式", test_safe_result),
        ("formula_list_all", test_formula_list_all),
        ("get_stock_list", test_get_stock_list),
        ("get_trading_dates", test_get_trading_dates),
        ("get_match_stkinfo", test_get_match_stkinfo),
        ("get_sector_list", test_get_sector_list),
        ("formula MACD 单股票", test_formula),
        ("错误处理", test_error_handling),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    sys.exit(0 if failed == 0 else 1)
