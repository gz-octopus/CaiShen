# -*- coding: utf-8 -*-
"""CaiShen MCP Server — 通达信数据能力的 MCP 协议封装。

启动方式：
    python D:/quant/CaiShen/caishen_mcp/server.py

Claude Code 配置（.claude/settings.local.json）：
    {
      "mcpServers": {
        "caishen": {
          "command": "python",
          "args": ["D:/quant/CaiShen/caishen_mcp/server.py"]
        }
      }
    }

前置条件：
    - 通达信客户端已打开并登录
    - PostgreSQL 服务已运行（入库操作需要）
"""

import sys
import os

# 确保项目根目录在 sys.path 中以支持相对 import
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP

from caishen_mcp.ctx_helper import init_tq_and_cache, check_tq_alive, safe_result

# ── 全局状态 ──
mcp = FastMCP("caishen")
_CFG: dict = {}
_DB_URL: str = ""
_CONSOLE = None


def get_server_state():
    """返回 server 全局状态，供各 tool 模块使用。"""
    return _CFG, _DB_URL, _CONSOLE


# ── 启动时初始化 ──
try:
    _CFG, _DB_URL, _CONSOLE = init_tq_and_cache()
    print(f"[caishen-mcp] TQ 初始化成功，已缓存股票和板块名称", file=sys.stderr)
except Exception as e:
    print(f"[caishen-mcp] TQ 初始化失败: {e}", file=sys.stderr)
    print("[caishen-mcp] 请确认通达信客户端已打开并登录", file=sys.stderr)
    sys.exit(1)


# ── 公用 helper: 所有 tool 的 TQ 存活门 ──
def require_tq():
    """检查 TQ 存活，若已断连则抛 RuntimeError。"""
    if not check_tq_alive():
        raise RuntimeError("通达信 TQ 连接已断开，请确认客户端是否仍在运行")


# ── 注册 tool 模块（导入即注册） ──
# 这些导入会触发各 tool 模块的 @mcp.tool() 装饰器，将函数注册到 FastMCP
from caishen_mcp.tools import formula_tools    # noqa: E402, F401
from caishen_mcp.tools import data_tools       # noqa: E402, F401
from caishen_mcp.tools import sector_tools     # noqa: E402, F401
from caishen_mcp.tools import sync_tools       # noqa: E402, F401
from caishen_mcp.tools import slb_tools        # noqa: E402, F401
from caishen_mcp.tools import win_rate_tools   # noqa: E402, F401


# ── 入口 ──
if __name__ == "__main__":
    mcp.run()
