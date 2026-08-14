# T4 tdxquant 补充数据适配方案

> 研究票编号：T4 ｜ 日期：2026-08-14 ｜ 验证人：wayfinder ｜ 目标架构：hikyuu 2.8.1 + tdxquant（D:\new_tdx_tet）
>
> 结论先行：三个补充数据接口（财务/板块/公式批量）链路可用性已实测；**财务数据本机客户端尚未下载（接口返回空），是财务因子方案的第一前置**；板块与公式批量即时可用。消费形态沿用第一闭环的轻量直取模式（sys.path 注入 + tqcenter），不 import 现有 REPL 框架。

---

## ① 财务：get_financial_data（专业财务）

### 接口实测结论（2026-08-14）

| 项 | 结论 |
|---|---|
| 返回结构 | `dict{股票代码: DataFrame}`，列 = 请求的 FN 字段（大写）+ `announce_time`（公告日 YYYYMMDD）+ `tag_time`（报告期截止日） |
| 字段体系 | FN1~FN584 专业财务字段（资产负债表/利润表/现金流量/比率指标/业绩预告/机构持股等），按需 `field_list` 筛选 |
| **前置条件** | **客户端必须先下载专业财务数据**（客户端「盘后数据下载」勾选）；本机实测 600519.SH 返回 `{'announce_time': None, 'tag_time': None}`（空 DataFrame，无报错）——**空数据静默返回，与权息表为空同类的坑，必须校验非空** |
| report_type | `announce_time`（按公告日期）/ `tag_time`（按报告期）——**PIT（point-in-time）关键参数**：回测若按公告日期对齐可避免未来函数，按报告期会提前使用未披露数据 |

### 财务因子数据方案（决策点）

- **建议：落库（快照）+ PIT 对齐**。理由：第一闭环验收 6 的可复现性（固定日期重跑逐位一致）要求数据快照固定；即取即用模式下财务数据随客户端下载更新而变化，回测不可复现。落库形态沿用 CaiShen 现有 PostgreSQL 惯例（history_data_1d / stock_metrics 同款），字段名保持 FN 编号 + 映射字典（中文名）。
- 增量维护：财报季（4/8/10 月末）后重跑拉取；入库管道复用 tdxdata REPL 的 db 管道模式。
- 消费路径：因子计算从库读（历史回放），tq 直取仅用于验证/最新数据。
- 注意：空数据校验（无记录视为未下载，拒绝回测，同权息校验模式）。

### 复用关系

- tdxdata_cmd.py 已有 `get_financial_data` 命令（tdxdata_cmd.py:1177）——人工查询/入库场景直接用它。

## ② 板块：get_stock_list_in_sector

### 接口实测结论（2026-08-14）

| 项 | 结论 |
|---|---|
| 入参 | 板块指数代码/名称（block_type=0）或自定义板块简称（block_type=1，如 ZXG 自选股）；**不支持系统「全部A股/沪深A股」板块**（须用 get_stock_list(market) 代替） |
| 返回 | list_type=0 纯代码列表；list_type=1 代码+名称 dict 列表 |
| 实测 | 「钛金属」24 只（含北交所 920068.BJ），与文档样本一致且更新 |

### 选股池过滤用法

- 板块成分列表 → 转 hikyuu 证券（`hku.sm[code]`）→ 过滤停牌/ST（停牌由 hikyuu 自然跳过，ST 过滤需 tq.get_stock_info 或现有 tdxdata 工具）→ 作为回测股票池（组合路径，T7 范畴；第一闭环单标的用不上）。
- 落点：内存列表即可（板块列表小、即时可变）；hikyuu Block 表（stock.db 的 Block 表当前为空）非必需。

### 复用关系

- tdxdata_cmd.py 已有封装（tdxdata_cmd.py:1530，含 block_type=2 期货支持）；strategy_research 内需要时按同模式轻量封装。

## ③ 公式批量：formula_process_mul_xg / mul_zb

### 接口实测结论（2026-08-14）

| 项 | 结论 |
|---|---|
| 返回结构 | `dict{股票代码: {输出名: [{'Date': 'YYYYMMDD', 'Value': str}]}}` + `ErrorId`；选股公式输出名带参数（如 UP3） |
| 关键参数 | `dividend_type` 0 不复权/1 前复权/2 后复权——**与 hikyuu 对齐：FORWARD=1**；`count=-1` 全量（return_count=0 时受 start/end 限制）；`return_count=1` 只取最新值（选股判断够用） |
| 前置 | 盘后数据完整下载（客户端每日自动）；`stock_period` 支持 1d 等 |
| 实测 | UPN 选股公式 3 只股票正常返回，结构符合文档 |

### 作 hikyuu 结果验证的用法

- 对齐口径：同一公式、同一标的、同一区间、同一复权（dividend_type=1 ↔ hikyuu Query.FORWARD），比对 date→value 序列。
- 验证对象：T6 翻译器的输出、或 strategy_research 内通达信公式二等表达的计算结果。
- 量级：批量多股一次调用返回全部股票结果，单次 IPC 往返，适合全市场扫描验证。

### 复用关系

- tdxdata_cmd.py 的 `formula` / `formula_multi` 命令（tdxdata_cmd.py:850 起）已封装公式调用 + stock_metrics 入库管道——人工场景直接用；回测链路内的验证调用在 strategy_research 内按轻量模式封装（同 check.py 的 tqcenter 直取模式）。

## ④ 消费形态与复用边界（结论）

- **strategy_research 不 import tdxdata_repl/tdxdata_cmd**（避免引入 REPL 框架与内存缓存层，同第一闭环原则）；需要 tq 数据时按 check.py 既有模式：`sys.path` 注入 PYPlugins → `tqcenter.tq` 直取，工具函数放 strategy_research 内独立模块（T7 落地时建 `tdxdata.py`）。
- **边界**：tdxdata REPL = 人工交互 + 数据入库管道（PostgreSQL）；strategy_research = 回测链路内的按需直取 + 校验。两者共用同一 tqcenter 客户端，不共用代码。

## ⑤ 风险清单（补充）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| 1 | 专业财务数据未下载 | 财务接口静默返回空（无报错） | 使用前校验非空（同权息校验模式）；客户端下载专业财务数据 |
| 2 | 财务 PIT 错位 | 按报告期使用未披露数据（未来函数） | report_type=announce_time + 因子计算按公告日期对齐 |
| 3 | 板块接口不支持系统板块 | 「全部A股」类选股池拿不到 | 用 get_stock_list(market) 替代 |
| 4 | 公式结果与客户端不一致 | 验证结论失真 | K 线数量须充足（count 参数，文档明示）；复权类型对齐 |

## ⑥ 交付给 T7 的决策点

- 财务因子数据形态：**建议落库快照**（可复现性），最终由 T7 定稿。
- 板块选股池：内存列表（不建议进 hikyuu Block 表）。
- 公式验证自动化程度：全市场批量比对 vs 抽样比对，T7 定。
