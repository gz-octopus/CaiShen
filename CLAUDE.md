# CLAUDE.md

此文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指导。

## 项目概述

一套 A 股量化交易 CLI 工具集 — 涵盖数据获取、技术指标计算、策略回测和风险分析（扫雷宝/SLB）。以独立 Python 脚本形式构建，而非可安装的 Python 包。

**技术栈：** Python 3.12、click + click_shell（交互式 REPL）、rich（终端 UI）、pandas/numpy/scipy、SQLAlchemy（PostgreSQL/SQLite）、vectorbt、TA-Lib。

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

`init()` 回调接收 `click.Context`，将全局变量（`CONSOLE`、`CFG`、DB URL）存入 `ctx.obj`（一个 `defaultdict`），并初始化数据源客户端。

`repl_cli_main()` 支持两种可选模式（通过参数启用）：

- `find_caller_cmds=True` — 自动从调用模块发现 `@click.command()` 函数，无需单独的 `_cmd.py` 文件
- `command_with_abbrev` 装饰器 — 为命令定义缩写（如 `cmd` → `c`、`history` → `h`）

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
    CONSOLE = _ctx.obj['console']
    try:
        # 命令逻辑
        ...
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)
```

要点：
- `context_settings` 固定为 `{'help_option_names': ['-?', '--help', '-h']}`
- 第一个参数必须为 `_ctx: click.Context`（配合 `@click.pass_context`）
- `ctx.obj` 始终包含三个键：`config_path`、`console`、`cfg`
- 异常处理使用 `CONSOLE.print_exception(extra_lines=5, show_locals=True)`
- `split_comma_stocks` 是用于 `multiple=True` 股票代码选项的标准 callback，会将输入自动解析并补全市场后缀（如 `603358` → `603358.SH`）

## 安全注意事项

`config.yaml` 中包含明文 API token 和数据库密码。注意不要将真实凭据提交到版本控制。建议使用环境变量替代敏感值，或将 `config.yaml` 加入 `.gitignore`。
