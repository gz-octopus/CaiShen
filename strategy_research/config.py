# -*- coding: utf-8 -*-
"""配置管理：仓库根 config.yaml 的 hikyuu 组 + hikyuu 初始化。

路径解析规则：
- config.yaml 中 hikyuu 组的相对路径以 config.yaml 所在目录（仓库根）为基准；
- 未配置或为空时回退到包内默认（strategy_research/ 下自包含）。

config.yaml 可选追加格式（全部项可不配，默认值即下方 DEFAULT_* 常量）：

    hikyuu:
      ini_path: strategy_research/hikyuu.ini   # hikyuu 原生配置，留空则用包内默认
      report_dir: strategy_research/reports    # 报告输出目录，留空则用包内默认
      init_cash: 1000000                       # 初始资金
      cost_func: TC_FixedA2017                 # 交易成本函数
      slippage: 0.001                          # 滑点 0.1%（SP_FixedPercent）
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from difoss_stock_util import I, W

# 包根目录（strategy_research/）
PKG_DIR = Path(__file__).resolve().parent
# 仓库根目录（config.yaml 所在，包目录的父级）
REPO_DIR = PKG_DIR.parent
# 仓库根 config.yaml
CONFIG_YAML = REPO_DIR / 'config.yaml'

# 回测默认值（与 config.yaml 可选项一一对应）
DEFAULT_START = '2020-01-02'          # 回测起始（本地数据最早交易日）
DEFAULT_END = '2026-08-13'            # 回测结束（最新交易日）
DEFAULT_STOCK = 'sh000001'            # 上证指数
DEFAULT_INIT_CASH = 1_000_000         # 初始资金 100 万
DEFAULT_COST_FUNC = 'TC_FixedA2017'   # 交易成本函数
DEFAULT_SLIPPAGE = 0.001              # 滑点 0.1%（SP_FixedPercent）
DEFAULT_FAST_N = 10                   # MA 快线
DEFAULT_SLOW_N = 30                   # MA 慢线

# 回测产物固定文件名（backtest 落盘 / report 读取共享；放 config 避免 backtest↔report 循环导入）
RESULT_JSON = 'backtest_result.json'
FUNDS_PNG = 'funds_performance.png'
DRAWDOWN_PNG = 'drawdown.png'
DEFAULT_REPORT_NAME = 'first_loop_report.html'


@dataclass
class HikyuuConfig:
    """config.yaml hikyuu 组 + 包内默认值的合并结果（非敏感参数）。"""
    ini_path: Path = field(default_factory=lambda: PKG_DIR / 'hikyuu.ini')
    report_dir: Path = field(default_factory=lambda: PKG_DIR / 'reports')
    init_cash: float = DEFAULT_INIT_CASH
    cost_func: str = DEFAULT_COST_FUNC
    slippage: float = DEFAULT_SLIPPAGE


def _resolve_repo_relative(value: str | None, default: Path) -> Path:
    """相对路径以仓库根（config.yaml 目录）为基准；空值回退包内默认。"""
    if not value or not str(value).strip():
        return default
    p = Path(str(value))
    if not p.is_absolute():
        p = REPO_DIR / p
    return p


def load_config(config_path: Path | str | None = None) -> HikyuuConfig:
    """读取仓库根 config.yaml 的 hikyuu 组，未配置项回退默认值。

    注意：
    - config.yaml 含明文凭据，本函数只读取 hikyuu 组，
      不读取、不打印、不落盘其他任何配置值。
    - 不用 difoss_stock_util.read_yaml_config：其全文件环境变量展开会因
      config.yaml 其他组（slb 等）的占位符在无 .env 环境时抛 ValueError
      （2026-08-14 实测），此处仅需 hikyuu 组，yaml.safe_load 即可。
    """
    import yaml

    cfg = HikyuuConfig()
    if config_path is None:
        config_path = CONFIG_YAML
    if not Path(config_path).exists():
        W(f'config.yaml 不存在（{config_path}），全部使用默认配置')
        return cfg

    with open(config_path, encoding='utf-8') as f:
        raw = yaml.safe_load(f) or {}
    hk = raw.get('hikyuu') or {}
    if not isinstance(hk, dict):
        W('config.yaml 中 hikyuu 组格式异常（应为字典），忽略并使用默认配置')
        hk = {}

    cfg.ini_path = _resolve_repo_relative(hk.get('ini_path'), PKG_DIR / 'hikyuu.ini')
    cfg.report_dir = _resolve_repo_relative(hk.get('report_dir'), PKG_DIR / 'reports')
    if hk.get('init_cash') is not None:
        cfg.init_cash = float(hk['init_cash'])
    if hk.get('cost_func'):
        cfg.cost_func = str(hk['cost_func'])
    if hk.get('slippage') is not None:
        cfg.slippage = float(hk['slippage'])
    return cfg


def init_hikyuu(config: HikyuuConfig | None = None) -> HikyuuConfig:
    """初始化 hikyuu 全局系统（StockManager 等）。

    必须最先调用 matplotlib.use('Agg') 再 import hikyuu（无 GUI 环境出 PNG 必需）。
    hikyuu 初始化开销大，重复调用自动跳过。
    """
    import matplotlib
    matplotlib.use('Agg')

    import hikyuu as hku

    if config is None:
        config = load_config()

    # load_hikyuu 幂等保护：已初始化时 hiku 内部会直接返回
    ini = str(config.ini_path)
    if not config.ini_path.exists():
        raise FileNotFoundError(f'hikyuu.ini 不存在: {ini}')
    hku.load_hikyuu(config_file=ini)
    I(f'hikyuu 初始化完成（ini: {ini}）')
    return config


def ensure_dirs(config: HikyuuConfig) -> None:
    """确保报告输出目录存在（data/tmp 由 hikyuu 初始化时创建）。"""
    config.report_dir.mkdir(parents=True, exist_ok=True)
