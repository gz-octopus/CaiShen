# strategy_research — 策略研究回测系统

CaiShen 仓库内的 A 股量化研究子系统（hikyuu 2.8.1 主架构）。提供从**数据 → 因子 → 策略 → 回测 → 报告**的完整研究通路：

- **数据**：hikyuu 原生驱动直读通达信客户端日线（不落库），权息（分红送配）唯一落库
- **因子**：`factors/` 因子库，量化研究中的因子，通达信中的指标，统一称为因子
- **策略**：`strategies/` 策略库，由因子+仓位管理组成策略
- **回测**：回测统一执行器，回测因子或策略
- **报告**：回测报告 html（Performance 53 项 + 自算夏普/回撤 + 图表内嵌）
- **留痕**：每次回测自动登记回测信息到实验记录表，回测产物按次归档不覆盖

## 目录结构

```
strategy_research/
├── __main__.py            CLI 入口（python -m strategy_research）
├── backtest.py            策略回测执行器：股票池过滤、执行、结果提取、落盘、写实验记录
├── run_factor.py          因子评估执行器：IC/ICIR + 分层回测 + 评估报告
├── check.py               数据就绪校验（tdxw 进程 + 权息抽样）
├── config.py              配置加载 + hikyuu 初始化（含 matplotlib Agg 前置）
├── report.py              报告渲染（夏普/回撤纯函数 + jinja2 html）
├── factors/               因子库（资产统一放此目录，见下方「扩展新资产」）
│   ├── __init__.py        因子登记处：FACTOR_BUILDERS（名称→构建函数）/ FACTOR_META（元数据）
│   └── tech.py            具体因子实现--技术类因子
├── strategies/            策略库（资产统一放此目录）
│   ├── base.py            数据类（StrategyConfig/BuiltStrategy）与策略登记表
│   ├── ma_cross.py        单标的 MA(10)/MA(30) 金叉择时
│   └── tech5.py           五因子等权 + Zscore + TopN 月度组合
├── experiments/           实验参数文件（记录回测时的策略参数）
│   ├── ma_cross.yaml      单标的基线实验
│   └── tech5.yaml         组合基线实验
├── report/                报告模板（回测报告 + 因子评估报告）
├── hikyuu.ini             hikyuu 原生配置（K 线直读 D:\TDX\vipdoc）
├── data/                  数据（stock.db 权息库、experiments.db 实验记录表、tmp）
├── _selfcheck/            系统自检（下划线前缀=开发保障设施，非研究资产）：
│   │                      单元测试 test_strategy_research.py / 回归验收 verify_t7.py
└── reports/               回测产物（回测报告 + 因子评估报告）
```

## 基础架构

```
通达信客户端（tdxw.exe 运行中）
   │
   ├─ vipdoc 日线 ──→ hikyuu TdxKDataDriver 直读（不落库，FORWARD 前复权）
   ├─ 权息 getdividfactors ──→ data/stock.db stkWeight 表（唯一落库，check 强制校验）
   │
   ▼
factors/ 因子（hku.Factor：name + Indicator + 元数据）
   ▼
strategies/ 策略组装（hikyuu 组件）：
  单标的    SE_Fixed([标的], 原型System) + AF_EqualWeight + PF_Simple
  组合      MF 合成 → NORM 归一化 → SE_MultiFactor2(SCFilter TopN) → AF → PF
   ▼
backtest.py 统一执行（pf.run → 提取 53 项/资金曲线/成交/调仓 → 落盘 + 登记实验记录）
   ▼
reports/<日期>_<策略>_<参数>_<runid>/ 产物 + report.html（单文件自包含）
```

## 环境准备

### 依赖

依赖清单：

| 依赖 | 版本 | 说明 |
|---|---|---|
| hikyuu | 2.8.1 | 回测引擎（C++ 内核） |
| click / rich | — | CLI 框架 / 终端表格 |
| pandas / numpy | — | 数据处理 |
| matplotlib | — | 图表渲染（hikyuu 绘图引擎） |
| jinja2 | — | html 报告模板 |
| pyyaml | — | 实验参数文件解析 |

安装（新机器一次到位）：

```powershell
python -m pip install hikyuu==2.8.1 click rich pandas matplotlib jinja2 pyyaml
```

验证：

```powershell
python -c "import hikyuu; print(hikyuu.__version__)"   # 2.8.1
```

### 数据前置

- 通达信客户端（tdxw.exe）**运行中**——权息接口与每日数据更新依赖它
- K 线目录 `D:\TDX\vipdoc`（勿迁移到中文路径——hikyuu 直读会静默失败，可在hikyuu.ini 中修改）
- 权息库 `strategy_research/data/stock.db` 已导入（check 命令强制校验，空表拒绝回测）

## 快速开始

```powershell
cd D:\quant\CaiShen

# 单标的 MA 金叉回测 + 报告
python -m strategy_research backtest -c strategy_research/experiments/ma_cross.yaml --report

# 五因子组合回测 + 报告（全市场月度调仓）
python -m strategy_research backtest -c strategy_research/experiments/tech5.yaml --report

# 因子评估（IC/ICIR + 10 层分层，约 8 分钟）
python -m strategy_research factor
```

## 命令参考

| 命令 | 用途 |
|---|---|
| `python -m strategy_research check` | 数据就绪校验（不通过拒绝回测） |
| `python -m strategy_research backtest [选项]` | 统一回测 |
| `python -m strategy_research factor [选项]` | 因子评估，出 html 评估报告 |
| `python -m strategy_research report <结果目录> [-o 路径]` | 从落盘结果重新渲染报告 |

### backtest 选项

| 选项 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `-c, --config` | 路径 | — | 实验参数文件（YAML） |
| `-s, --strategy` | `ma-cross` / `tech5` | `tech5` | 策略 slug |
| `--topn` | 整数 | 10 | 组合选股数 |
| `--mf` | `equal-weight` / `icir-weight` | `equal-weight` | 因子合成方式 |
| `--norm` | `zscore` / `quantile-uniform` / `minmax` / `nothing` | `zscore` | 归一化 |
| `--adjust-mode` | `month` / `query` / `day` | `month` | 调仓模式（month=自然月） |
| `--adjust-cycle` | 整数 | 1 | month 模式 = 每月第 N 日 |
| `--start` / `--end` | `YYYY-MM-DD` | 2020-01-02 / 2026-08-13 | 回测区间 |
| `--init-cash` | 数值 | 1000000 | 初始资金 |
| `--skip-check` | — | — | 跳过就绪校验（不推荐） |
| `--report` | — | — | 回测后自动出报告 |

参数优先级：**CLI 显式 > 实验 YAML > 默认值**——临时改参数不必改文件：

```powershell
python -m strategy_research backtest -c strategy_research/experiments/tech5.yaml --topn 20 --mf icir-weight
```

### 实验参数文件（experiments/*.yaml）

```yaml
strategy: tech5          # 策略 slug
topn: 10                 # 组合选股数
mf: equal-weight         # equal-weight | icir-weight
norm: zscore             # zscore | quantile-uniform | minmax | nothing
adjust_mode: month       # month | query | day
adjust_cycle: 1          # 月度调仓日
start: '2020-01-02'
end: '2026-08-13'
init_cash: 1000000
exclude_st: true         # 剔除 ST/*ST
min_listed_days: 60      # 剔除上市不满 60 自然日
min_active_days: 20      # 剔除近 20 日零成交（长期停牌近似）
factors: []              # 因子子集（空 = 全部注册因子）
```

股票池过滤自动附加代码前缀白名单（SH 60/68、SZ 00/30），排除指数/基金等非股票标的。

## 研究工作流（典型步骤）

1. **选因子**：`factor` 命令评估全部注册因子的 IC/ICIR/分层收益，筛选有预测力的因子
2. **定实验**：把策略+因子子集+参数写成 `experiments/xxx.yaml`
3. **跑回测**：`backtest -c experiments/xxx.yaml --report`，产物自动归档、实验记录自动登记
4. **看报告**：report.html 六个区块（头部参数+T+1 声明/指标卡×6/资金曲线 vs 基准/回撤曲线/53 项统计/交易明细），组合模式多调仓明细区块
5. **对比**：实验记录表查历史 run 的 summary，或者查看报告，报告目录按参数标签区分
6. **迭代**：改 YAML 或加新因子/新策略，重复 1-5

## 扩展新资产

**新因子**：在 `factors/` 新建模块，函数返回 `hku.Factor(name, indicator, brief=...)`；然后在 `factors/__init__.py` 的 `FACTOR_BUILDERS` 字典里登记（名称 → 构建函数），并在 `FACTOR_META` 里登记元数据（direction：positive/negative/neutral）。**「因子注册」就是这个字典登记**——策略按名引用因子，CLI 校验存在性，登记后即对全部策略可用。

**新策略**：在 `strategies/` 新建文件，实现 `build(cfg, stks) -> BuiltStrategy`（组装 MF/SE/SCF/AF/PF 组件，参考 tech5.py），在 `strategies/__init__.py` 的 `STRATEGY_BUILDERS` 字典登记 slug，`STRATEGY_META` 登记名称与描述。股票池过滤与执行由 backtest.py 统一负责，策略文件只写组装。

## 产物与实验留痕

```
reports/20260817_tech5_t10_000007/
├── backtest_result.json    # 全量结果（53 项/资金曲线/回撤/成交/调仓明细）
├── report.html             # 单文件自包含报告
├── funds_performance.png   # 资金曲线（vs sh000001 基准）
└── drawdown.png            # 回撤曲线
```

目录名 = `<日期>_<策略>_<参数标签>_<runid>`；`reports/factor_report.html` 为因子评估报告（固定名覆盖）。


## 验收与测试

```powershell
python strategy_research/_selfcheck/verify_t7.py              # 回归测试：系统验收自动重跑
python strategy_research/_selfcheck/test_strategy_research.py # 单元测试：指标纯函数
```

系统验收基线（回归参照）：ma-cross 单标的——夏普 -0.2224289778 / 最大回撤 34.68696762% / 60 笔交易 / 期末资产 822621.31。

## 已知约束

| # | 事项 | 说明 |
|---|---|---|
| 1 | 前复权口径 | FORWARD；运行日志「未来函数」警告为已知行为 |
| 2 | T+1 | 次日开盘执行模型下自动满足（买卖间隔 ≥1 交易日）；分钟级场景需另行实现 |
| 3 | 换手率因子不可用 | TURNOVER/HSL 依赖流通股本（数据缺失），已用 20 日量比替代 |
| 4 | 权息表为空 | 静默使用未复权价（高危），check 强制校验拒绝回测 |
| 5 | 财务因子未启用 | 需客户端下载专业财务数据后接入 |
| 6 | factor 命令耗时 | 全市场约 8 分钟（2583 只 × 5 因子） |
| 7 | 成本缓冲 | 组合原型 MM_FixedPercent(0.99)：p=1.0 时买入金额+成本超现金被拒买 |
