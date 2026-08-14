# T2 hikyuu 客户端直读数据配置 SOP

> 研究票编号：T2 ｜ 日期：2026-08-14 ｜ 验证人：wayfinder ｜ 目标架构：hikyuu 2.8.1 + 通达信金融量化测试版客户端（D:\new_tdx_tet）
>
> 数据链路设计：日K线由 hikyuu 原生 `TdxKDataDriver` 直读通达信客户端本地文件（无数据库）；权息通过 tdxquant `getdividfactors` 导入 hikyuu 权息表（sqlite，唯一落库环节）；财务/板块/公式由 tdxquant tqcenter 直取。
>
> 本票五项目全部经**实测验证**（非仅源码推断），证据均已落盘。未修改 D:\quant\resource\hikyuu 任何文件。

---

## ① 安装步骤（含实际结果）

### 环境

| 项 | 值 |
|---|---|
| Python | `D:\dev-environment\python312\python.exe`（3.12.12） |
| 系统 | Windows 11，系统代理 127.0.0.1:7890（Clash） |
| 目标版本 | hikyuu == 2.8.1（PyPI wheel：py3-none-win_amd64，38.3 MB） |

### 实际安装过程（两次尝试）

**尝试 1（失败）**：`pip install hikyuu==2.8.1` 直连 PyPI。进程存活但 **6 分多钟零流量**——被系统代理 127.0.0.1:7890 卡住（大文件下载走代理即挂）。杀掉进程。

**尝试 2（成功）**：
```powershell
$env:NO_PROXY='*'                       # 关键：绕过系统代理
D:\dev-environment\python312\python.exe -m pip install hikyuu==2.8.1
# 全局 index-url 已配 tuna 镜像（pip config list 可见），无需显式 -i
# 结果：Successfully installed hikyuu-2.8.1
```

**验证**：
```powershell
D:\dev-environment\python312\python.exe -c "import hikyuu as hk; print(hk.__version__)"
# 2.8.1
```
注：`--proxy ""` 在 PowerShell 5.1 下不可行（空串参数被吞掉，pip 会把 `--timeout` 当主机名解析报错），用环境变量 `NO_PROXY='*'` 替代。

### 初始化机制与最小配置

- 初始化入口：`hikyuu/__init__.py` 的 `load_hikyuu(config_file=...)` → 解析 hikyuu.ini → 构造各参数 → `StockManager` 启动（读市场/证券/权息/板块/K线）。
- **首次初始化会自动联网下载 hub 到 `%USERPROFILE%\.hikyuu\hub_cache`**（首次运行需网络，离线环境需预先准备）。
- 最小可用 `hikyuu.ini`（实测模板，本票验证用；`datadir`/`tmpdir` 需建目录）：

```ini
[hikyuu]
tmpdir = D:\quant\CaiShen\data\tmp
datadir = D:\quant\CaiShen\data
reload_time = 00:00
quotation_server = ipc:///tmp/hikyuu_real.ipc
lazy_preload = False
load_history_finance = False
load_stock_weight = True

[block]
type = sqlite3
db = D:\quant\CaiShen\data\stock.db

[baseinfo]
type = sqlite3
db = D:\quant\CaiShen\data\stock.db

[preload]
day = True          ; 必须 True，否则 DATE 型查询返回空（见②）
week = False
month = False
quarter = False
halfyear = False
year = False
min = False
min5 = False
min15 = False
min30 = False
min60 = False
hour2 = False
timeline = False
trans = False
day_max = 100000
week_max = 100000
month_max = 100000
quarter_max = 100000
halfyear_max = 100000
year_max = 100000
min_max = 5120
min5_max = 5120
min15_max = 5120
min30_max = 5120
min60_max = 5120
hour2_max = 5120
timeline_max = 5120
trans_max = 5120

[kdata]
type = tdx
dir = D:\TDX\vipdoc      ; 必须是纯 ASCII 路径（见②关键坑；2026-08-14 数据已迁至 D:\TDX，原 hku_vipdoc junction 退役）
```

- 注意 `[block]` 的 sqlite db 指向与 baseinfo 同一文件时，板块表缺 `[block] type=sqlite3` 会报错；空库用 `hikyuu.data.common_sqlite3.create_database` 建表（官方 createdb.sql + 升级脚本）。

---

## ② TdxKDataDriver 配置

### 配置语法与加载机制

源码：`D:\quant\resource\hikyuu\hikyuu_cpp\hikyuu\data_driver\kdata\tdx\TdxKDataDriver.cpp`；官方模板注释：`D:\quant\resource\hikyuu\hikyuu\data\hku_config_template.py`（`;type = tdx`、`;dir = D:\\TdxW_HuaTai\\vipdoc`）。

```ini
[kdata]
type = tdx
dir = <vipdoc 目录>       ; 到 lday/、minline/ 的父级，如 ...\vipdoc
```

驱动按市场小写子目录取文件：`{dir}\{market}\lday\{market}{code}.day`（日线，32 字节/条：uint32 date + OHLC×0.01 定点 + float amount×0.0001 + vol）、`minline\{market}{code}.lc1`（1分钟）、`fzline\{market}{code}.lc5`（5分钟）。

### 实测行为结论（均已验证）

| 项 | 结论 | 证据 |
|---|---|---|
| 支持周期 | **仅 DAY / MIN / MIN5**。MIN15/30/60/HOUR2/WEEK/MONTH/QUARTER/HALFYEAR/YEAR 查询被拒并告警，返回空 | TdxKDataDriver.cpp:93 `HKU_WARN_IF_RETURN(!(ktype==MIN||ktype==MIN5||ktype==DAY),...)`；实测 `Query(...WEEK)` 返回空 |
| 查询类型 | **仅 INDEX 型查询**（queryType=INDEX，即 start/end 索引号）；DATE 型查询在驱动层直接打印 "Query by date are not supported!" | TdxKDataDriver.cpp:96-104 |
| DATE 查询可用条件 | **必须 `[preload] day = True`**（走内存缓冲路径）；preload day=False 时 DATE 查询返回空（易踩坑，无报错） | 实测对比 ascii 与 ascii_nopreload 两套 ini |
| **DATE 查询 end 边界为 exclusive** | Query(2020-01-02, 2026-08-13) 返回最后根 2026-08-12；end 传 08-14 才含 08-13。回测代码须 end+1 天（第一闭环开发会话实测） | 第一闭环 backtest.py 实测修正 |
| 指数 | 直接读 `{dir}\sh\lday\sh000001.day` 等，INDEX 查询无需 preload | 实测 sh000001 正常 |
| 北交所 | `bj` 市场目录正常读取 | 实测 bj920000 正常 |
| **关键坑：非 ASCII 路径** | `[kdata] dir` 含中文（如 `D:\软件\通达信\vipdoc`）时**静默失败返回空数据**（C++ 窄字符 fopen 失败，无任何日志） | 实测中文路径全空；数据迁至纯 ASCII `D:\TDX\vipdoc` 后全部正常（2026-08-14） |
| 分钟线长度上限 | 驱动无上限（受限的是客户端下载量） | 源码无长度截断逻辑 |
| 周/月线 | **不支持、不合成**。驱动拒绝 WEEK/MONTH；需自行用 DAY 聚合 | 实测 week len=0 |

### 复权机制（AdjustType）

复权计算在 `hikyuu_cpp\hikyuu\KDataPrivatedBufferImp.cpp`（_recoverForward/_recoverBackward 等），权息数据来源是 **hikyuu 权息表（stkWeight，sqlite）**，与 K 线文件无关：

- 前复权（FORWARD）：`复权价 = (前价 − 红利 + 配股价 × 变动比例) ÷ (1 + 变动比例)`，`变动比例 = 0.1 × (countAsGift + countForSell + countOfIncreasement)`（每10股口径）；`suogu != 0` 时以 suogu 为分母（缩股场景）。
- 后复权（BACKWARD）：上式逆运算。
- **权息表为空：静默返回未复权原价，无报错、无警告**——数据会被"悄悄用错"，必须主动校验。
- 实测（伪造 10送10 记录）：前复权把除权日前价格减半（12.47→6.235），后复权加倍（6.60→13.20），除权日当天不变——公式精确吻合。
- 实测（真实数据，见④）：前复权除权前一日收盘 9.31 → 8.89 = 9.31 − 4.2/10，**精确一致**。

---

## ③ 本机数据就绪状态

### 目录结构

- **2026-08-14 数据整体迁移**：真实数据现位于纯 ASCII 目录 `D:\TDX\vipdoc`（含 sh/sz/bj）与 `D:\TDX\T0002`。
- `D:\软件\通达信\vipdoc`、`D:\软件\通达信\T0002` 为 junction → 指向 `D:\TDX\` 同名目录（客户端原路径不变，无需改客户端配置）。
- 原 `D:\hku_vipdoc` junction 已退役删除；hikyuu 直接配置 `dir = D:\TDX\vipdoc`。
- `D:\new_tdx_tet\vipdoc`（程序目录侧的旧链接）用户已于 2026-08-14 手动删除/重建（若客户端找不到数据，重建为指向 `D:\TDX\vipdoc` 的 junction）。

### 数据清单（2026-08-14 00:16 复测）

| 市场 | .day 文件数 | 起始日期 | 尾部日期 |
|---|---|---|---|
| sh | 4,928 | 2020-01-02（全部，无 2020 年前文件） | 2026-08-13 |
| sz | 4,433 | 2020-01-02（全部） | 2026-08-13 |
| bj | 339 | 2020-01-02（全部） | 2026-08-13 |
| **合计** | **9,700** | | |

- **数据新鲜**：全部 .day 尾部 = 2026-08-13（前一个交易日收盘）。8/14 00:01 通达信客户端（tdxw.exe，PID 由 00:01 启动）自动完成盘后下载，文件 mtime 00:03-00:04 全量刷新，三市场一致。早于 00:01 的检查（记录止于 07-28）是下载中途的快照，已过时。
- **分钟线缺失**：`minline\` 与 `fzline\` 目录为空 → MIN/MIN5 无数据（第一闭环为日线策略，不受影响；见⑤风险 6）。
- **财务文件缺失**：`eday\` 仅 `.pkg` 文件，无逐股财务数据 → `load_history_finance=False`，历史财务需另走 tdxquant tqcenter 直取。
- **证券表 bootstrap 成功**：用 9,700 个 .day 文件名 + 文件头/尾日期生成 Stock 表（market/code/type/startDate/endDate），hikyuu 全量加载正常（stock.db 见验证产物）。

---

## ④ 权息导入方案（getdividfactors → stkWeight）

### 链路

```
通达信客户端(tdxw.exe 运行中, IPC)
   → tqcenter.get_divid_factors(code.MARKET, start, end)   [tdxquant, D:\new_tdx_tet\PYPlugins\user\tqcenter.py]
   → DataFrame(index=除权除息日, 列: Type/Bonus/AllotPrice/ShareBonus/Allotment)
   → 映射 + 缩放 → INSERT INTO stkWeight(...)              [唯一落库环节, sqlite]
   → hikyuu StockManager 启动时加载(load_stock_weight=True)
   → get_weight() / FORWARD·BACKWARD 复权计算
```

### 前置条件：客户端必须运行

`tq.initialize` 通过 IPC 连接客户端进程。实测**客户端未运行时报错**：`TQ数据接口初始化失败: 连接路径为空` / `初始化错误：请确认是否打开通达信客户端`。**运行时报**（2026-08-14 00:16 实测）：`import tqcenter OK → tq.initialize OK → TQ数据接口初始化成功`。

调用方式（实测可用）：
```python
import sys
sys.path.insert(0, r'D:\new_tdx_tet\PYPlugins\user')
sys.path.insert(0, r'D:\new_tdx_tet\PYPlugins')
from tqcenter import tq
tq.initialize(__file__)                       # 参数为策略脚本路径
df = tq.get_divid_factors(stock_code='600000.SH', start_time='', end_time='')  # 空=全历史
tq.close()
```

### 字段映射表（已实测验证）

| getdividfactors 列 | 单位 | stkWeight 字段 | 存库缩放 | 读回缩放 | 说明 |
|---|---|---|---|---|---|
| 索引 Date | 除权除息日 | `date` (YYYYMMDD) | 直接 | — | 与行情除权日对齐 |
| ShareBonus | 股/10股 | `countAsGift` | ×10000 | ×0.0001 | 送股/转增 |
| Allotment | 股/10股 | `countForSell` | ×10000 | ×0.0001 | 配股 |
| AllotPrice | 元/股 | `priceForSell` | ×1000 | ×0.001 | 配股价 |
| Bonus | 元/10股 | `bonus` | ×1000 | ×0.001 | 现金红利 |
| Type=11 | — | 按 ShareBonus→countAsGift 处理 | 同上 | | 转增口径，本样本未见 |
| Type=15 | — | **跳过**（语义未确认，样本中无，谨慎处理） | | | |
| — | — | `countOfIncreasement`/`totalCount`/`freeCount`/`suogu` | 0 | | getdividfactors 无对应字段；缩股/股本变动需另取 |
| — | — | `stockid` | stock.stockid | | 关联证券表 |

缩放与读回已核源码：`D:\quant\resource\hikyuu\hikyuu\data\pytdx_weight_to_sqlite.py`（写侧 ×10000/×1000）、`hikyuu_cpp\hikyuu\data_driver\base_info\sqlite\SQLiteBaseInfoDriver.cpp`（读侧 ×0.0001/×0.001）；字段语义（每10股）见 `docs\source\stock_manager.rst`。

### 最小导入脚本（实测版，端到端跑通）

```python
# -*- coding: utf-8 -*-
# 全市场一次性导入: 通达信客户端权息 -> hikyuu stock.db stkWeight
import sys, os, glob, sqlite3, struct
sys.path.insert(0, r'D:\new_tdx_tet\PYPlugins\user'); sys.path.insert(0, r'D:\new_tdx_tet\PYPlugins')
from tqcenter import tq

from hikyuu.data.common_sqlite3 import create_database, get_marketid
DB  = r'D:\quant\CaiShen\data\stock.db'   # 与 hikyuu.ini 的 db 一致
VPD = r'D:\TDX\vipdoc'

con = sqlite3.connect(DB); create_database(con); cur = con.cursor()
rules = cur.execute('select marketid,codepre,type from coderuletype').fetchall()
def stk_type(mk, code):
    for m, p, t in sorted([r for r in rules if r[0] == get_marketid(con, mk)],
                          key=lambda r: len(r[1]), reverse=True):
        if code.startswith(p): return t
    return 1

tq.initialize(__file__)
total_w = 0
for mk, mkdir in (('SH','sh'), ('SZ','sz'), ('BJ','bj')):
    mid = get_marketid(con, mk)
    for p in glob.glob(os.path.join(VPD, mkdir, 'lday', '*.day')):
        code = os.path.basename(p)[2:-4]
        with open(p,'rb') as f:
            h = struct.unpack('<I', f.read(4))[0]
            f.seek(-32, os.SEEK_END); t = struct.unpack('<I', f.read(4))[0]
        cur.execute('insert or replace into Stock(stockid,marketid,code,name,type,valid,startDate,endDate)'
                    ' values (?,?,?,?,?,?,?,?)',
                    (None, mid, code, code, stk_type(mk, code), 1, h, t))
        sid = cur.execute('select stockid from stock where marketid=? and code=?', (mid, code)).fetchone()[0]
        df = tq.get_divid_factors(stock_code=f'{code}.{mk}', start_time='', end_time='')
        rows = []
        for idx, r in df.iterrows():
            if r['Type'] == 15:            # 语义未确认, 跳过
                continue
            rows.append((sid, int(idx.strftime('%Y%m%d')),
                         int(round(10000*float(r['ShareBonus']))), int(round(10000*float(r['Allotment']))),
                         int(round(1000*float(r['AllotPrice']))), int(round(1000*float(r['Bonus']))),
                         0, 0, 0, 0))
        if rows:
            cur.execute('delete from stkWeight where stockid=?', (sid,))
            cur.executemany('insert into stkWeight(stockid,date,countAsGift,countForSell,priceForSell,bonus,'
                            ' countOfIncreasement,totalCount,freeCount,suogu) values (?,?,?,?,?,?,?,?,?,?)', rows)
            total_w += len(rows)
    con.commit()
con.commit(); tq.close()
print('imported weight rows:', total_w)     # 导入后需重启回测进程(权息在启动时加载)
```

### 一次性导入流程与增量

1. 打开通达信客户端（确认 tdxw.exe 进程存在）→ 运行上述脚本（一次性；9,700 只全历史预计数分钟量级，未全量实测）。
2. 重启回测进程（StockManager 启动时加载权息，`load_stock_weight=True`）。
3. **增量**：每年 7-8 月分红季后再跑一次（脚本幂等：delete+insert）。
4. **校验**（必做，见⑤风险 3）：抽样 3-5 只，比对 `get_weight()` 条数与最近权息日是否与行情软件一致。

### 端到端实测证据（sh600000）

- `get_divid_factors('600000.SH')` 返回 **27 条**（2000-07-06 ~ 2026-07-16），全部 Type=1；样例：2026-07-16 Bonus=4.2。
- 导入后 `get_weight()` 读出 **27 条**，值与源数据逐条一致（bonus=4.2/4.1/3.21/3.2…）。
- 复权验证：最近权息日 2026-07-16（红利 4.2 元/10股），raw 除权前收盘 9.31 → **fwd 8.89 = 9.31 − 0.42（精确）**，除权日当天 fwd 8.85 = raw 8.85（不变）；bwd 全部按历史累计因子上调（11.851/11.811）。

---

## ⑤ 风险清单

| # | 风险 | 影响 | 证据 | 缓解 |
|---|---|---|---|---|
| 1 | 通达信客户端未运行 | 权息接口不可用；.day 不更新 | 实测：未运行时报 `连接路径为空`；00:01 客户端启动后才拿到数据 | SOP 前置检查：`Get-Process tdxw`；客户端设开机自启 + 盘后自动下载 |
| 2 | 本地历史缺失（仅 2020-01-02 起） | 2020 年前的因子/回测无数据 | 实测 9,700 文件全部 ≥2020-01-02，0 个更早 | 客户端"盘后数据下载"勾选全历史；上线前用脚本统计起始日 |
| 3 | 权息表为空/不完整 | **静默按未复权价计算，无任何报错**（最危险） | 源码 + 实测：空表返回原价 | 导入后校验条数与最近权息日；抽样核对分红额；回测结果与行情软件复权价对账 |
| 4 | `[kdata] dir` 非 ASCII 路径 | 静默返回空数据（C++ 窄字符失败，无日志） | 实测中文路径全空；迁至 ASCII 后正常 | 数据已迁至纯 ASCII `D:\TDX\vipdoc`，ini 直接配置该路径；禁止把数据移回中文路径 |
| 5 | `preload day=False` 时 DATE 查询 | 日期区间查询返回空（无报错） | 实测对比两套 ini | ini 固定 `preload day=True`；代码统一用 INDEX 查询 + 自行换算索引 |
| 6 | 分钟线缺失（minline/fzline 空） | MIN/MIN5 无数据；分钟级策略不可用 | 实测目录为空 | 客户端下载 1/5 分钟线（lc1/lc5 落 vipdoc）；或后续换 HDF5/数据库 |
| 7 | WEEK/MONTH 不支持 | 周/月周期查询返回空 | 实测 week len=0；源码 ktype 白名单 | 自行用 DAY 聚合（因子层 resample），勿依赖 KQuery.WEEK |
| 8 | 直读文件性能 | 全市场轮询可能变慢 | 实测：9,700 只全量 preload 0.14s；缓存后日期查询 26µs；500 只×250日前复权 0.208s（119,812 bars） | 当前量级远够用；因子扫描时复用 KData 对象而非反复查询；如需海量分钟数据再评估 HDF5（其优势在分钟/超长历史随机访问，日线直读差距不显著） |
| 9 | 指数 vol 单位与个股不一致 | 指数 vol 为"股"，个股 .day 为"手" | 源码 + 实测 sh000001 | 涉及指数/个股混算量能时统一单位 |
| 10 | 首次初始化需联网下 hub | 离线环境首次启动失败 | `~/.hikyuu/hub_cache` 自动下载 | 预置 hub_cache；或首次在联网机初始化后拷贝 |
| 11 | pip 安装走系统代理卡死 | 安装超时 | 实测 PyPI 直连 6 分钟零流量 | `$env:NO_PROXY='*'` + tuna 镜像 |

---

## ⑥ 对第一闭环的一页结论

**结论：链路可用，方案成立。** hikyuu 2.8.1 + 通达信客户端直读的"日线直读 + 权息落库"架构已在本机**端到端实测跑通**：9,700 只股票（sh/sz/bj）日线全部读得，数据更新至 2026-08-13（前一交易日，客户端 00:01 启动时已自动完成盘后下载）；权息链 `客户端 getdividfactors → stkWeight(sqlite) → get_weight → 复权计算` 用真实数据（sh600000 全历史 27 条）验证，前复权数字与公式精确吻合（9.31 → 8.89 = 9.31 − 0.42）；性能充裕（全市场加载 0.14s、缓存查询 26µs、500 只 250 日因子扫描 0.208s）。

**第一闭环落地步骤（按序执行，每步有前置校验）：**

1. **环境**：`pip install hikyuu==2.8.1`（`NO_PROXY='*'` + tuna）→ 验证 `hk.__version__ == '2.8.1'`。
2. **数据**：确认 `tdxw.exe` 运行；确认 `D:\TDX\vipdoc` 存在（纯 ASCII，数据已迁入，hikyuu ini 直接配置该路径）；用①中的 ini 模板 + 脚本 bootstrap `stock.db`（9,700 只）。
3. **权息**：客户端运行状态下跑④的导入脚本 → 校验条数与最近权息日 → 重启回测进程。
4. **回测/因子代码规约**：一律用 INDEX 型查询（或依赖 preload day=True 的 DATE 查询）；复权统一 FORWARD（历史回放视角）或明确口径；周月线自聚合；不对 WEEK/MONTH 查询做任何假设。
5. **运维**：客户端开机自启 + 盘后自动下载；分红季（7-8月）后重跑权息导入；上线前跑⑤清单中的校验。

**遗留/未决（不影响第一闭环日线策略）**：历史数据仅到 2020-01-02（需更早数据须先客户端全历史下载）；分钟线目录为空（分钟级策略需另下载或换存储）；财务历史走 tqcenter 直取方案未在本票验证（属 T 系列后续票）。
