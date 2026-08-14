---
id: T2
title: hikyuu 客户端直读数据配置 SOP
type: research
status: closed
blocked_by: []
---

## Question

核实并产出可照做的数据配置 SOP（本机 Python 3.12 / `D:\new_tdx_tet`）：

1. hikyuu 2.8.1 在本机 pip 安装（python312），记录实际安装步骤与耗时；网络慢时允许超时，记录错误即可。
2. `TdxKDataDriver` 启用方式：hku_config 配置（`[kdata] type=tdx; dir=...`）、支持的 ktype（日/1分/5分；周/月如何合成）、复权链路（hikyuu 复权机制：权息表位置、AdjustType 用法）。
3. 本机客户端数据就绪状态：`D:\new_tdx_tet` 下 vipdoc（或等价数据目录）是否存在、日线覆盖多少股票/多少年历史、缺失情况（新股/早期数据）。
4. 权息导入：tdxquant `getdividfactors` 返回格式（文档 `D:\cortex\02-Sources\articles\tdx-quant-docs\行情类信息\获取分红送配数据getdividfactors.md`）+ hikyuu 权息表导入工具（源码 `D:\quant\resource\hikyuu` 中 pytdx_weight_to_* / weight_to_sqlite.py），给出最小导入脚本思路。
5. 风险清单：数据缺失、复权错误、直读文件性能。

产出写入 `docs/wayfinder/research/T2-hikyuu客户端直读数据配置SOP.md`（含证据）；关闭本 ticket 时把结论同步到地图 Decisions so far。

## Resolution（2026-08-14，AFK research）

链路端到端实测可用，数据架构定稿成立：

- hikyuu==2.8.1 已在 python312 安装成功（pip 直连被系统代理卡死，`NO_PROXY='*'` + tuna 镜像解决）。
- `TdxKDataDriver` 实测：仅 DAY/MIN/MIN5（WEEK/MONTH 返回空）；仅 INDEX 查询直读，DATE 查询须 `preload day=True`；**dir 路径含中文会静默返回空数据**（已建 junction `D:\hku_vipdoc` 解决，SOP 固定件）。
- 本机数据就绪：9,700 只 .day（sh 4928 / sz 4433 / bj 339），全部起自 2020-01-02、尾部已刷新至最新交易日；minline/fzline 为空（无分钟线）。
- 复权链路端到端验证：客户端在线 → `getdividfactors` → 字段映射（ShareBonus×10000→countAsGift、Allotment×10000→countForSell、AllotPrice×1000→priceForSell、Bonus×1000→bonus，Type=15 跳过）→ 导入 stkWeight → hikyuu `get_weight()` 27 条逐条一致 → 复权数字精确（10送10 减半/加倍、真实分红 9.31→8.89 验证）。
- **最高危风险**：权息表为空时 hikyuu 静默用未复权价（无报错）——回测前必须校验权息表非空。
- 性能：全市场 preload 0.14s、缓存查询 26µs、500 只×250 日前复权扫描 0.208s（119,812 bars）——第一闭环量级远够用。
- 遗留：历史止于 2020（客户端下载范围）、分钟线缺失（均不影响日线策略）；验证脚本留存 `%TEMP%\hku_t2_check\`。
- 更新（T3 定稿后）：ini 模板 `datadir` 改为 `D:\quant\CaiShen\strategy_research\data`（系统全自包含在 strategy_research/ 包内，见 T3 定稿）；其余链路结论不变。
