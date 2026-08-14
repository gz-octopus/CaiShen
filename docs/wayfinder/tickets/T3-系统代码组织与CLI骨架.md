---
id: T3
title: 系统代码组织与 CLI 骨架
type: grilling
status: closed
blocked_by: [T1, T2]
---

## Question

系统在 CaiShen 仓库里的代码组织与入口设计：

1. 目录/包结构（独立包 `strategy_research/`？还是根目录脚本 + 模块？CaiShen 现有惯例是根目录独立脚本 + REPL 双文件）
2. hikyuu 配置管理（hku_config 放哪、如何初始化加载、与 CaiShen `config.yaml` 惯例的关系）
3. CLI 入口设计（命令集：数据就绪检查 / 回测 / 出报告？click 惯例）

产出：代码结构与 CLI 骨架方案。关闭后第一闭环可在开发会话中按此落地。

## Resolution（2026-08-14，grilling）

### 代码组织

- **独立包 `strategy_research/`**（仓库新目录，与现有 REPL 工具并列）——**代码/配置/数据/产物全部自包含在包内，根目录零新增**：
  - `strategy_research/__main__.py` — click group 入口（沿用 `context_settings={'help_option_names': ['-?', '--help', '-h']}` 惯例），调用方式 `python -m strategy_research`
  - `strategy_research/hikyuu.ini` — hikyuu 原生配置（T2 定稿模板，`datadir` 调整为 `D:\quant\CaiShen\strategy_research\data`；`[kdata] type=tdx dir=D:\TDX\vipdoc`、`[preload] day=True`、`load_stock_weight=True`）
  - 模块按功能拆分（执行会话细化）：`config.py`（config.yaml hikyuu 组 + hikyuu 初始化）、`check.py`（数据就绪校验）、`backtest.py`（System + TradeManager 回测）、`report.py`（Performance/夏普/回撤/html）、`strategy.py`（MA 金叉策略，按 T1 定稿）
  - `strategy_research/data/` — stock.db 权息库 + tmp（gitignore）
  - `strategy_research/reports/` — html 报告输出（gitignore）
- **依赖面**：click、rich、hikyuu、pandas + **按需复用 difoss_stock_util 现成工具**（`color_log_util` 单字符日志、`print_dataframe` 等直接复用）；**不引入** REPL 框架（click_shell）与内存缓存层——批处理场景不需要。
- 配置读取（执行修订 2026-08-14）：config.yaml 的 hikyuu 组用 **`yaml.safe_load` 只读该组**。原定复用 `read_yaml_config` 实测不可行——其全文件环境变量展开会因 config.yaml 其他组（slb 等）的占位符在无 .env 环境时抛 ValueError；strategy_research 只需 hikyuu 组，无 env 展开需求。

### 配置管理

- `strategy_research/hikyuu.ini`：hikyuu 原生格式独立文件，**不翻译成 YAML**；`datadir` 指向包内 `strategy_research/data`。
- 根 `config.yaml` 新增 `hikyuu:` 组（非敏感参数，沿 `read_yaml_config` 惯例）：ini 路径、报告输出目录（`strategy_research/reports/`）、初始资金 100 万、成本/滑点默认值（TC_FixedA2017 / SP 0.001）。
- `.gitignore` 增加 `strategy_research/data/` 与 `strategy_research/reports/`（生成物）。

### CLI 骨架

click group（包内 `__main__.py`，入口 `python -m strategy_research`）四个子命令：

| 命令 | 职责 |
|---|---|
| `check` | 数据就绪校验（T1 两项：tdxw 进程 + 权息非空抽样比对） |
| `backtest` | 跑回测，结果落盘 |
| `report` | 从回测结果出 html 报告 |
| `first-loop` | check → backtest → report 一键，**T1 验收物** |

- 四命令全部实现，first-loop 为前三者组合；交付顺序 first-loop 优先（第一闭环）。
- **验收命令**：T1 定稿「`python first_loop.py`」等价落地为 **`python -m strategy_research first-loop`**（不另建文件）。

### 落地约束（供执行会话）

- 中文注释/文档；click `context_settings` 惯例；单字符日志（复用 color_log_util）；rich 表格输出。
- 数据路径纯 ASCII（`D:\TDX\vipdoc`，T2 风险 4）；DATE 查询依赖 `preload day=True`（T2 风险 5）。
