---
id: T4
title: tdxquant 补充数据适配
type: research
status: open
blocked_by: [T1]
---

## Question

tdxquant（tqcenter）补充数据的消费方案：

1. 财务：`get_financial_data`（专业财务）返回结构；第一闭环用于查询/验证（不进 hikyuu 引擎）；**财务因子**的数据方案在此定（是否落地、落哪种形态、如何被因子计算消费）
2. 板块：`getstocklistinsector` 成分股列表作为选股池过滤的用法
3. 公式：`formulaprocessmul_xg-zb-exp` 批量调用作 hikyuu 结果验证的用法
4. 与 CaiShen 现有 tdxdata 工具（tdxdata_repl/tdxdata_cmd 已有 tq 封装）的复用关系

产出：补充数据接入方案（含财务因子决策点）。关闭后 T7 因子流水线可引用。
