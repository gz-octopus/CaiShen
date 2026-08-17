# -*- coding: utf-8 -*-
"""bool 型因子实现：0/1 条件表达式。

bool 型因子与数值型因子同构，都是返回 hku.Factor 的构建函数，
区别仅在 FACTOR_META 的 value_type（bool → 事件研究评估通路）。
hikyuu 无逻辑与运算符，0/1 条件指标相乘即为与逻辑。
"""
from __future__ import annotations

import hikyuu as hku


def build_limitup_vol2_yin() -> hku.Factor:
    """涨停次日倍量阴：前日收盘封板，当日成交量达前日 2 倍且收阴。

    冲板成功次日高开回落放巨量，主力出货的常见形态。
    事件日 = 阴线日；事件后收益从阴线次日开盘起算。
    """
    cond_limitup_prev = hku.REF(hku.ISLIMITUP(), 1)          # 前日收盘封板
    cond_vol2 = hku.VOL() / hku.REF(hku.VOL(), 1) >= 2       # 当日量 ≥ 前日 2 倍
    cond_yin = hku.CLOSE() < hku.OPEN()                       # 当日收阴
    return hku.Factor('limitup_vol2_yin', cond_limitup_prev * cond_vol2 * cond_yin,
                      brief='涨停次日倍量阴')
