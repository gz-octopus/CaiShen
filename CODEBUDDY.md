# CODEBUDDY.md

此文件为 WorkBuddy (CodeBuddy Code) 在此仓库中工作时提供指导。

> 由 `CLAUDE.md` 迁移而来（2026-08-19）。`CLAUDE.md` 保留，用于 Claude Code 双轨并行；两份文件内容应保持同步。

## 项目概述

一套 A 股量化交易 CLI 工具集 — 涵盖数据获取、技术指标计算、策略回测和风险分析（扫雷宝/SLB）。以独立 Python 脚本形式构建，而非可安装的 Python 包。

**技术栈：** Python 3.12、click + click_shell（交互式 REPL）、rich（终端 UI）、pandas/numpy/scipy、SQLAlchemy（PostgreSQL/SQLite）、vectorbt、TA-Lib、hikyuu。

## 运行方式

每个工具都是独立的脚本，直接用 Python 启动：

### 交互式 REPL 工具

```bash
python tdxdata_repl.py          # 通达信数据工具（主力）— 交互式 REPL，提示符：tdx>
python tdxdata_repl.py <cmd>    # 单次批处理命令
python slb_repl.py              # 扫雷宝风险分析 — 交互式 REPL，提示符：slb>
python xtquant_repl.py          # QMT/迅投数据工具 — 交互式 REPL，提示符：xt>
python tushare_repl.py          # Tushare 数据工具 — 交互式 REPL，提示符：ts>
python win_rate_repl.py         # 胜率分析工具 — 交互式 REPL
python mootdx_repl.py           # mootdx 数据工具 — 交互式 REPL
python pytdx_repl.py            # pytdx 数据工具 — 交互式 REPL
python mt5_repl.py              # MetaTrader5 数据工具 — 交互式 REPL
python difoss_stock_util_repl.py  # difoss_stock_util 功能测试（SecurityCode 等）
```

### 独立脚本（非 REPL）

```bash
python slb_detail.py            # 扫雷宝详情查看器（比较不同日期的 SLB 数据）
python slb_to_files.py          # 扫雷宝数据导出到文件
python slb_migration.py         # 扫雷宝数据库迁移（原始 SQL 同步）
python stock_classify.py        # 股票代码分类器（按数字/字母模式分类）
python strategy_bt.py           # vectorbt MA 交叉回测示例
python 2year_double_positive.py # 两年双阳模式回测（使用 akshare）
python stock_instrument_detail_to_db.py  # 合约详情入库
```

### 策略研究子系统

```bash
python -m strategy_research check     # 数据/环境就绪校验
python -m strategy_research backtest  # 策略回测（统一执行器，单标的=股票池1特例）
python -m strategy_research report    # 生成报告
python -m strategy_research factor    # 因子评估（-f <因子名> 只评单个）
```

## 测试方式

所有测试和探索脚本统一放在 `test/` 目录下。无正式测试运行器，直接运行单个文件：

```bash
python test/test_trading_info.py        # 基于 unittest（最完整的测试，269 行）
python test/test_history_improved.py    # REPL 集成测试（演示 command_with_abbrev 模式）
python test/test_enum_decorator.py      # enum 装饰器测试
```

探索性脚本（`test/t_*.py`，共 23 个）是临时实验，非正式测试。

## 第三方库安装

本项目依赖的部分库非官方版本，官方原版已长期未维护，由作者自行修复和 fork。这些库通过**符号链接**方式安装到 site-packages，便于开发调试：

```bash
# 查看所有符号链接的包（自动定位 site-packages）
SITE_PACKAGES=$(python -c 'import site; print(site.getsitepackages()[0])')
ls -l "$SITE_PACKAGES" | grep ' -> '
```

| 包名 | 来源 | 安装方式 |
|------|------|----------|
| `pytdx` | `github.com/difosschan/pytdx`（fork） | `git clone` 后 `ln -s` 到 site-packages |
| `simple_pytdx` | `github.com/difosschan/simple_pytdx`（fork） | 同上 |
| `tdx_quant` | 通达信金融量化测试版安装目录 `PYPlugins/user` | 安装通达信金融量化测试版后，`ln -s` 到 site-packages |
| `difoss_stock_util` | 本地开发路径 `difoss-stock-util` | `ln -s` 到 site-packages |
| `xtquant` | 迅投官方 SDK（`xtquant-250516`） | 官方安装包 + `ln -s` |

> **注意：** `pytdx` 和 `simple_pytdx` 与 PyPI 上的同名包不兼容，必须从对应的 GitHub 仓库安装。`tdx_quant` 需要先安装通达信金融量化测试版客户端。

## 架构

### REPL 优先模式

每个数据源或功能领域遵循双文件拆分：

- **`*_repl.py`** — 入口点。通过 `repl_cli_main()`（来自 `difoss_stock_util.click_util`）定义交互式 shell。包含 `init()` 回调函数，用于设置全局状态（配置、数据库连接、数据源客户端）。直接运行。
- **`*_cmd.py`** — 命令定义，以 `@click.command()` 装饰函数形式存在。由 `repl_cli_main()` 通过 `cmd_filenames` 参数加载。

`init()` 回调接收 `click.Context`，将全局变量（`CONSOLE`、`CFG`、DB URL）存入 `ctx.obj`（一个 `defaultdict`），并初始化数据源客户端。从 ctx.obj 中获得的局部变量，为了不想被 print_locals() 打印出细节，需要使用 _ 开头的命名（如：`_CSL`、`_CFG`），全局变量则可直接用 global 引入（不会被 print_locals() 打印）。

`repl_cli_main()` 支持两种可选模式（通过参数启用）：

- `find_caller_cmds=True` — 自动从调用模块发现 `@click.command()` 函数，无需单独的 `_cmd.py` 文件
- `command_with_abbrev` 装饰器 — 为命令定义缩写（如 `cmd` → `c`、`history` → `h`）

### 策略研究子系统（`strategy_research/`）

独立包，批处理场景，不沿用 REPL 框架。代码组织：

- `factors/` — 因子库（返回 hky Factor 对象，目录扫描注册）+ `strategies/` — 策略库；两层纯代码，不做声明式 spec
- `backtest.py` — 统一回测执行器（单标的=股票池 1 的特例）
- `run_event.py` — 因子事件研究（截面统计、等权、无资金无费用）
- `experiments/` — 每次实验一个 YAML 参数文件进 git；CLI 优先级：显式参数 > config > 默认
- 实验注册表 SQLite（run_id/参数快照/commit hash/指标摘要）+ 产物目录 `reports/<日期>_<slug>_<参数>_<runid6>/`

事件研究 vs 策略回测的边界与使用时机见 `docs/adr/0001-event-study-vs-strategy-backtest.md`。

### 外部依赖：`difoss_stock_util`

核心库以 site-package 形式安装于 `D:\develop_tool_\Python\Python312\Lib\site-packages\difoss_stock_util\`。主要模块：

| 模块 | 用途 |
|---|---|
| `click_util.py` | `repl_cli_main()` 框架、Click 辅助函数、字段过滤/表格打印、`split_comma_stocks` 回调 |
| `color_log_util.py` | 单字符日志函数：`E`、`W`、`I`、`D`、`T`、`P` |
| `db_util.py` | SQLAlchemy 引擎/Base/CRUD 工具 |
| `security_util.py` | `SecurityCode`、`SecurityType`、`MarketType`（MetadataEnum 基类） |
| `stock_util.py` | `TradingInfo`（支持 `complete()` 自动补全）、交易日计算 |
| `time_util.py` | `TimeUtils` |
| `xtquant_util.py` | xtquant SDK 封装 |
| `slb_file_mgr.py` | 扫雷宝文件管理器（继承自 `security_json_file_util`） |
| `security_json_file_util.py` | `SecurityJsonFileNaming` / `SecurityJsonFileManager` 基类 |
| `iquant_util.py` | iQuant/QMT 辅助工具 |
| `network_util.py` | 端口检测（`check_port()` 用于 miniQMT 连接） |
| `dir_util.py` | 递归目录遍历（`walk()`、`get_file_info()`） |
| `BJ_change_code_2025_10_09.py` | 北交所 2025 年代码变更（87/83/43 → 920 前缀） |
| `tdx_util/` | TDX 板块/行业解析器、数据字典、公式计算函数 |
| `rich_util/` | 进度条、富文本表格（当前活跃：`fixed_progress_simple_v2_Qwen3Max`） |
| `metric_data/` | ORM 模型：`SLBDetail`、`HistoryData1D`、`StockInstrumentDetail` |
| `util.py` | `read_yaml_config`、`print_locals`、`trace_func`/`trace_function` 装饰器 |

大多数脚本通过 `from difoss_stock_util import *` 导入（扁平命名空间重导出）。

### 内存缓存（`cache_cmd.py`）

提供跨 REPL 会话共享的全局可变状态：`STOCKS`（set）、`GROUPED_STOCKS`（defaultdict）、`STOCKS_DF`（DataFrame）、`STOCK_2_DF`（DataFrame 字典）、`_STOCK_2_NAME`（代码→名称映射）。通过 `threading.RLock` 保证线程安全。装饰器 `stocks_collector`、`df_collector`、`memory_cache` 自动将命令结果填充到这些全局变量中。

### 配置

项目根目录的 `config.yaml` 存储数据库凭据、数据目录路径、API 令牌和服务器 IP。通过 `difoss_stock_util.util.read_yaml_config()` 加载。另有 `mini_config.yaml`（精简版）和 `fuck.yaml`（完整版，不同 PostgreSQL 主机）。

### Click-Shell 兼容性补丁

每个使用 `click_shell` 且 click ≥ 8.1 的 `*_repl.py` 文件必须在所有其他 click 导入之前包含以下猴子补丁：

```python
import click.core
_original_parameter_init = click.core.Parameter.__init__
def _patched_parameter_init(self, *args, **kwargs):
    kwargs.pop('callable', None)
    return _original_parameter_init(self, *args, **kwargs)
click.core.Parameter.__init__ = _patched_parameter_init
```

此为必需，因为 `click_shell` 传递了 `click>=8.1` 不接受的 `callable` 关键字参数。

### 数据库模式

`difoss_stock_util.db_util` 提供 `init_db()`、通过 `generate_engine_url_str()` 创建引擎，以及 ORM 模型的 `TimestampsMixin`。模型位于 `difoss_stock_util.metric_data`，采用基于类方法的 active-record 风格（例如 `HistoryData1D.batch_insert()`、`HistoryData1D.get_all()`）。

### 数据源模式

每个外部数据源（TDX/通达信、QMT/迅投、Tushare、mootdx、MT5）都有各自的 REPL 入口点，封装不同的 SDK。TDX 工具（`tdxdata_repl.py`）是主要且功能最完整的工具，支持公式计算、板块分析和数据库同步。它依赖 `tdx_quant` 包（`tdx_quant.tqcenter.tq`）进行实际数据连接。

### 数据流依赖

跨文件的导入关系（修改导入时需注意避免循环依赖）：

- `xtquant_repl.py` → 导入 `tdxdata_repl.py` 的 `cache_stock_name_of_market()`
- `tdxdata_repl.py` → 导入 `cache_cmd.py` 的 `cache_stock_name` / `cache_st_stock_name`
- `tdxdata_cmd.py` → 导入 `tdx_quant_util.py`（中文板块名 → 拼音首字母缩写转换）

## 关键约定

- **日志：** 使用 `difoss_stock_util.color_log_util` 中的单字符函数（`E`、`W`、`I`、`D`、`T`、`P`），通过 `_level` 关键字参数进行分类。
- **表格输出：** 使用 `difoss_stock_util.click_util` 中的 `print_dataframe()` 通过 rich 输出格式化 DataFrame。
- **字段名：** 原始数字 TDX 字段索引需加前缀（例如 `42` → `FN42`），通过 `_fix_fields()` 实现。
- **版本头：** 许多文件在头部注释块中记录变更历史，包含版本号和日期。
- **中文为主要语言：** 注释、文档和 CLI 输出均使用中文。

### CLI 命令约定

所有 click 命令遵循统一模式：

```python
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, ...)
@click.pass_context
def some_command(_ctx: click.Context, stocks: list[str], ...):
    """命令说明（中文）"""
    _CSL = _ctx.obj['console'] # # type: console.Console
    try:
        # 命令逻辑
        ...
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)
```

要点：
- `context_settings` 固定为 `{'help_option_names': ['-?', '--help', '-h']}`
- 第一个参数必须为 `_ctx: click.Context`（配合 `@click.pass_context`）
- `ctx.obj` 始终包含三个键：`config_path`、`console`、`cfg`
- 异常处理使用 `_CSL.print_exception(extra_lines=5, show_locals=True)`
- `split_comma_stocks` 是用于 `multiple=True` 股票代码选项的标准 callback，会将输入自动解析并补全市场后缀（如 `603358` → `603358.SH`）

## 安全注意事项

`config.yaml` 中包含明文 API token 和数据库密码。注意不要将真实凭据提交到版本控制。建议使用环境变量替代敏感值，或将 `config.yaml` 加入 `.gitignore`。

## 硬规则（用户明确反馈，违反即不合格）

1. **不自动 git**：所有 git 写操作（commit/push/merge/branch）必须先征得用户明确同意，只准备（暂存/草稿 message）不执行。
2. **用户可见文档禁开发阶段词**：「第一/第二闭环」「第 N 阶段」等开发过程术语不得出现在 README/CLI 帮助/报告/注释中，用实质描述替代（如「单标的基线回归」）。
3. **注释只写「是什么/为什么」**：禁计划步骤式注释、ticket 编号/定稿引用、TODO 清单、临时方案留痕。详见 `docs/agents/code-conventions.md`。

## Agent 调用（MCP）

本项目的 MCP server 位于 `caishen_mcp/server.py`，通过 MCP 协议将 28 个数据工具暴露给 AI agent（Claude Code / WorkBuddy）。

### Server 信息

- 入口：`python D:/quant/CaiShen/caishen_mcp/server.py`（stdio / JSON-RPC）
- 工具数：28 个（公式、数据、板块、同步、风险五组）
- 前置条件：通达信客户端必须已打开并登录（TQ 组件依赖它）；PostgreSQL 服务已启动（入库操作需要）；`pip install mcp>=1.0.0`

### Claude Code 注册方式（参考）

原 `.claude/settings.local.json` 中注册：

```json
{
  "mcpServers": {
    "caishen": {
      "command": "python",
      "args": ["D:/quant/CaiShen/caishen_mcp/server.py"]
    }
  }
}
```

WorkBuddy 中如未接入该 MCP，需通过 MCP 配置将 `caishen_mcp/server.py` 注册为本地 stdio server。

### Tool 分组速览

| 分组 | Tool | 用途 |
|------|------|------|
| 公式 | `formula`, `formula_list_all`, `formula_multi` | 通达信公式计算/选股 + 可选入库 |
| 数据 | `get_stock_metrics`, `get_market_data`, `get_stock_list`, `get_match_stkinfo`, `get_stock_info`, `get_more_info`, `get_market_snapshot`, `get_financial_data`, `get_divide_factors`, `get_ipo_info`, `get_gb_info`, `get_cb_info`, `get_trading_dates`, `get_gpjy_value`, `get_bkjy_value`, `get_scjy_value`, `stock_block_stat`, `stock_stat` | 行情、财务、交易数据查询 |
| 板块 | `get_sector_list`, `get_stocks_in_sector`, `get_user_sector_list`, `get_user_sector_stocks` | 板块和成分股查询 |
| 同步 | `sync_history` | 全市场日 K 同步到 PG |
| 风险 | `slb_query`, `win_rate_report` | 扫雷宝风险分析 + 胜率报告 |

Agent 通过 MCP 协议自动发现完整的 tool schema（参数名、类型、描述），无需手动查阅本文档的参数细节。

## 规则文档索引

以下文档是本仓库 agent 写代码/做决策时的强制约定，按需查阅：

- **代码规范**（注释/命名/结构）：`docs/agents/code-conventions.md`
- **域文档消费规则**：`docs/agents/domain.md`
- **Issue tracker 约定**（GitHub + gh CLI）：`docs/agents/issue-tracker.md`
- **Triage 标签映射**：`docs/agents/triage-labels.md`
- **架构决策记录**：`docs/adr/`（当前 ADR-0001：因子事件研究 vs 策略回测边界）
- **Wayfinder 设计会话**：`docs/wayfinder/`（map.md + research/ + tickets/）
- **长期记忆与硬规则**：`.workbuddy/memory/MEMORY.md`
- **技术决策详情**（历史）：`D:\cortex\04-Projects\CaiShen\_memory\decisions.md`
