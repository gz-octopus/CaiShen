---
id: T4
title: tdxquant 补充数据适配
type: research
status: closed
blocked_by: [T1]
---

## Question

tdxquant（tqcenter）补充数据的消费方案：

1. 财务：`get_financial_data`（专业财务）返回结构；第一闭环用于查询/验证（不进 hikyuu 引擎）；**财务因子**的数据方案在此定（是否落地、落哪种形态、如何被因子计算消费）
2. 板块：`getstocklistinsector` 成分股列表作为选股池过滤的用法
3. 公式：`formulaprocessmul_xg-zb-exp` 批量调用作 hikyuu 结果验证的用法
4. 与 CaiShen 现有 tdxdata 工具（tdxdata_repl/tdxdata_cmd 已有 tq 封装）的复用关系

产出：补充数据接入方案（含财务因子决策点）。关闭后 T7 因子流水线可引用。

## Resolution（2026-08-14，AFK research）

三接口链路实测 + 方案定稿，详见 docs/wayfinder/research/T4-tdxquant补充数据适配方案.md：

- **财务**：返回 dict{code: DataFrame[FN 字段 + announce_time/tag_time]}，FN1~584 字段体系；**本机客户端尚未下载专业财务数据，接口静默返回空**（同权息空表同类的坑，必须校验非空）；财务因子数据方案**建议落库快照 + PIT（announce_time）对齐**（可复现性要求），最终形态 T7 定
- **板块**：实测「钛金属」24 只正常；仅支持自定义板块/15 板块指数，系统「全部A股」须用 get_stock_list 替代；选股池过滤用内存列表，不进 hikyuu Block 表
- **公式批量**：实测 UPN 选股公式正常；返回 {code: {输出名: [{Date, Value}]}}；作 hikyuu 验证时复权对齐 dividend_type=1 ↔ FORWARD
- **复用边界**：strategy_research 不 import tdxdata REPL（避免引 REPL 框架），按 check.py 轻量直取模式（sys.path 注入 + tqcenter）独立封装；tdxdata REPL 保持人工交互/入库管道定位
