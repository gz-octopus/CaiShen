# Wayfinder Map — CaiShen 策略研究回测系统（hikyuu 主架构）

> 本地 markdown tracker：地图与 ticket 均为本目录下的 markdown 文件，无 tracker 查询机制，ticket 索引见文末表格。
> ticket 状态以各文件 frontmatter `status` 为准（open / claimed / closed），阻塞以 `blocked_by` 为准。

## Destination

在 CaiShen 仓库内构建一套以 hikyuu 2.8.1（pip，Python 3.12 / Windows）为主架构的 A 股策略研究回测系统：
通达信 K 线经 hikyuu 原生 `TdxKDataDriver` 直读客户端文件（不落库、不改 C++）；权息（分红送配）经 tdxquant `getdividfactors` 导入 hikyuu 权息表（唯一落库）；财务/板块/公式经 tdxquant 直取（Python 层即取即用）；策略以 hikyuu 原生 Python（组件体系）为一等表达，通达信公式为二等表达并双向互转（常用子集，翻译器不进第一闭环）；回测全在 hikyuu 事件驱动框架内，组合走官方 multifactor→Portfolio 路径（不引入 vectorbt）；报告 = Performance 53 项（hikyuu 2.8.1 实测）+ 自算夏普/最大回撤 + html 汇总（CLI 一键出、notebook 可选）；与 quant_lab 零关系；远期交易通道走 tdxquant。

## Notes

- **领域**：A 股量化研究回测。框架=hikyuu 2.8.1（源码参考 `D:\quant\resource\hikyuu`）；数据=通达信客户端 + tdxquant（官方文档镜像 `D:\cortex\02-Sources\articles\tdx-quant-docs\`）。
- **环境**：Python 3.12（`D:\dev-environment\python312`）；通达信金融量化测试版 `D:\new_tdx_tet`；hikyuu 用 pip 稳定版，源码仓库仅查证。
- **数据架构（已定稿）**：K 线不落库（TdxKDataDriver 直读客户端 vipdoc）；权息唯一落库（getdividfactors → hikyuu 权息表）；财务/板块/公式 tqcenter 直取。
- **执行覆盖（Notes override）**：本 effort 不止出决策——「第一闭环」（数据→因子→策略→回测→报告最小通路）作为落地执行包含在地图内，由后续开发会话执行；地图 ticket 只解决决策。
- **会话惯例**：CaiShen 惯例（中文注释/文档、CLI 入口）；grilling 会话用 /grilling + /domain-modeling。
- **路线图**：第一闭环（T1 定义）→ 系统骨架（T3）→ 报告（T5）→ 因子流水线（T7）→ 公式翻译器（T6，目的地一部分但不进第一闭环）。
- **执行状态**：第一闭环已落地（2026-08-14，分支 first-loop）——`python -m strategy_research first-loop` 验收全过（T1 七条，含重跑逐位一致）；权息库 55,717 条 / 5,276 只已导入（stock.db 位于 strategy_research/data，gitignore）。

## Decisions so far

<!-- 每关闭一个 ticket，在此追加一行：[ticket 标题](tickets/xx.md) — 一句话结论 -->

- [hikyuu 客户端直读数据配置 SOP](tickets/T2-hikyuu客户端直读数据配置SOP.md) — 链路实测可用：hikyuu 2.8.1 装好；TdxKDataDriver 直读客户端文件（仅日线/1分/5分，dir 须纯 ASCII 路径 `D:\TDX\vipdoc`，2026-08-14 数据已迁至 D:\TDX，原 `D:\hku_vipdoc` junction 退役）；9700 只日线 2020 起；复权 getdividfactors→stkWeight 端到端验证精确；**权息表空时静默用未复权价（高危，回测前必须校验）**
- [第一闭环定义与验收](tickets/T1-第一闭环定义与验收.md) — 第一闭环=单标的 MA 金叉择时（sh000001，MA10/30）最小通路：就绪校验两项（tdxw 进程+权息抽样，不做尾部日期）；100 万/TC_FixedA2017+SP 0.1%/次日开盘成交；**MM_FixedPercent(0.99)（执行修订：p=1.0 被 hikyuu 成本溢出拒买）**；A 股规则仅一字板延迟+停牌（T+1 不做，显式记偏差）；报告=Performance 53 项（实测修正 44）+自算夏普/回撤+html（first_loop.py 一键，T3 收纳）；验收=可跑+sanity+重跑逐位一致；组合路径留 T7
- [系统代码组织与 CLI 骨架](tickets/T3-系统代码组织与CLI骨架.md) — 独立包 strategy_research/ 全自包含（代码+ini+data+reports 均在包内，根目录零新增；入口 python -m strategy_research，click 四子命令 check/backtest/report/first-loop）；config.yaml 新增 hikyuu 组；gitignore 包内 data/与 reports/；按需复用 difoss_stock_util（日志/表格），不引 REPL 框架；**配置读取改 yaml.safe_load 只读 hikyuu 组（执行修订：read_yaml_config 全文件 env 展开会失败）**；验收命令 = python -m strategy_research first-loop
- [tdxquant 补充数据适配](tickets/T4-tdxquant补充数据适配.md) — 财务/板块/公式批量三接口实测可用；财务须客户端先下载专业财务数据（否则静默空），方案建议落库快照+PIT；板块选股池走内存列表；公式验证复权对齐 dividend_type=1↔FORWARD；strategy_research 按轻量直取模式独立封装，不 import tdxdata REPL
- [公式翻译器子集原型](tickets/T6-公式翻译器子集原型.md) — 技术方案验证成立：300 行原型（词法+递归下降+映射生成）；翻译的 MA 金叉公式与第一闭环 SG_Cross 金叉日 30/30 完全一致；hikyuu 顶层 418 符号 TDX 兼容面宽（翻译核心是解析+映射）；正式模块化（strategy_research/translator.py）待 T7 需要时
- [报告层设计](tickets/T5-报告层设计.md) — 自算年化夏普（get_funds_curve 日收益×√252）+最大回撤（MDD 指标×**自实现算法**交叉验证——执行修订：get_max_pull_back 在 2.8.1 恒返回 0.0 不可用）；绘图=matplotlib（hikyuu 原生引擎，tm.performance 绑定方法打底；echarts 出局：2.8.1 缺陷+无 TM 绩效；引擎可插拔留 T7）；html=jinja2 单文件自包含（base64 内嵌，固定名 first_loop_report.html，--output 可指定）；6 区块布局含 T+1 偏差声明；坑：crtTM 构造 + import hikyuu 前 Agg + DATE 查询 end exclusive + get_funds_curve 须传 dates

## Not yet specified

- **回测产物归档**（多策略/多版本/多次回测分类存放）——现状为固定名覆盖（T5 定稿，第一闭环验收需要）；2026-08-14 用户决定**暂不做**，等 T7 因子流水线设计时一并决定归档方案（候选：运行目录归档 / 实验注册表）
- **多源扩展**（tushare/xtquant 等）——目的地只要求通达信，何时要、怎么接未定
- **参数优化/稳健性分析**——用户未要求，研究系统自然延伸，暂不承诺
- **交易通道与部署细节**（tdxquant 下单/订阅/预警，远期）
- **hikyuu 源码级定制**（C++ 改动）——Python 层优先，仅当真需要再议
- **vectorbt 按需挂载**——若日后大规模参数扫描需要矩阵式组合数学
- **数据约束补充**——历史止于 2020（客户端下载范围）、分钟线缺失（minline/fzline 空）；如第一闭环需要更早历史或分钟线，走 pytdx 导入路径补充（原 B 的备选路线）

## Out of scope

- **quant_lab 一切**（技术栈与方法论都不迁移）——失败作品，地图不留通向它的边
- **通达信公式全量语言**——翻译器只做常用子集（指标+选股公式常规语法），扩展公式/DLL 函数不做（T6 定稿）

## Tickets

| id | 标题 | 类型 | 状态 | 阻塞 |
|----|------|------|------|------|
| [T1](tickets/T1-第一闭环定义与验收.md) | 第一闭环定义与验收 | grilling | closed | — |
| [T2](tickets/T2-hikyuu客户端直读数据配置SOP.md) | hikyuu 客户端直读数据配置 SOP | research | **closed** | — |
| [T3](tickets/T3-系统代码组织与CLI骨架.md) | 系统代码组织与 CLI 骨架 | grilling | closed | T1, T2 |
| [T4](tickets/T4-tdxquant补充数据适配.md) | tdxquant 补充数据适配 | research | **closed** | T1 |
| [T5](tickets/T5-报告层设计.md) | 报告层设计 | grilling | closed | T1 |
| [T6](tickets/T6-公式翻译器子集原型.md) | 公式翻译器子集原型 | prototype | **closed** | T1 |
| [T7](tickets/T7-因子研究流水线接入.md) | 因子研究流水线接入 | grilling | open | T1, T5 |

**frontier（可认领）**：T7
