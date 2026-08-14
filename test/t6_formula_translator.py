# -*- coding: utf-8 -*-
"""T6 原型：通达信公式 ↔ hikyuu 翻译器（常用子集）。

子集（v0）：
- 字面量：数字
- 变量：OPEN/HIGH/LOW/CLOSE/VOL/AMO（及 O/H/L/C/V 缩写）
- 函数：MA/EMA/SMA/REF/REFX/CROSS/LONGCROSS/EVERY/EXIST/COUNT/HHV/LLV/
       IF/ABS/MAX/MIN/UPNDAY/DOWNNDAY/NDAY/BARSLAST/SUM
- 运算符：+ - * / > < >= <= = == != AND OR NOT 括号
- 参数定义：N:=10（声明式参数，映射为翻译参数）
- 选股公式语义：整条表达式为真 → 选中（hikyuu 侧可接 SG）

用法：
    python test/t6_formula_translator.py          # 跑自测（含真实数据执行验证）
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------- 词法分析

TOKEN_RE = re.compile(
    r'\s*(?:(?P<NUM>\d+(?:\.\d+)?)|(?P<NAME>[A-Za-z_][A-Za-z0-9_]*)|'
    r'(?P<OP>:=|>=|<=|==|!=|[-+*/()<>=,;:]))'
)


def tokenize(text: str) -> list[tuple[str, str]]:
    """公式文本 → [(类型, 值)]。非法字符抛 ValueError。"""
    tokens, pos = [], 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise ValueError(f'无法识别的字符: {text[pos]!r} (位置 {pos})')
        kind = m.lastgroup
        tokens.append((kind, m.group()))
        pos = m.end()
    return tokens


# ---------------------------------------------------------------- AST

@dataclass
class Num:
    value: float


@dataclass
class Var:
    name: str


@dataclass
class Call:
    name: str
    args: list


@dataclass
class Bin:
    op: str
    left: object
    right: object


@dataclass
class Unary:
    op: str
    operand: object


# ---------------------------------------------------------------- 语法分析

class Parser:
    """递归下降：expr := or_expr；or := and ('OR' and)*；and := cmp ('AND' cmp)*；
    cmp := add (比较符 add)?；add := mul (('+'|'-') mul)*；mul := unary (('*'|'/') unary)*；
    unary := '-' unary | 'NOT' unary | primary；primary := NUM | NAME | NAME'('args')' | '('expr')'
    """

    def __init__(self, text: str):
        self.tokens = tokenize(text)
        self.pos = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> tuple[str, str]:
        t = self.peek()
        self.pos += 1
        return t

    def expect(self, kind: str, value: str | None = None):
        t = self.peek()
        if t is None or t[0] != kind or (value is not None and t[1].upper() != value):
            raise ValueError(f'期望 {value or kind}，实际 {t}')
        return self.next()

    def parse(self) -> list[tuple[str, object]]:
        """返回语句列表：[(参数名, 表达式)] 或 [('', 表达式)]。"""
        stmts = []
        while self.peek() is not None:
            name = ''
            if self.peek()[0] == 'NAME' and self.tokens[self.pos + 1][1] == ':=' \
                    if self.pos + 1 < len(self.tokens) else False:
                name = self.next()[1]
                self.expect('OP', ':=')
            expr = self.parse_or()
            stmts.append((name, expr))
            if self.peek() is not None and self.peek()[1] == ';':
                self.next()
        return stmts

    def parse_or(self):
        left = self.parse_and()
        while self.peek() is not None and self.peek()[1].upper() == 'OR':
            self.next()
            left = Bin('OR', left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_cmp()
        while self.peek() is not None and self.peek()[1].upper() == 'AND':
            self.next()
            left = Bin('AND', left, self.parse_cmp())
        return left

    def parse_cmp(self):
        left = self.parse_add()
        t = self.peek()
        if t is not None and t[0] == 'OP' and t[1] in ('>', '<', '>=', '<=', '=', '==', '!='):
            op = self.next()[1]
            return Bin(op, left, self.parse_add())
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.peek() is not None and self.peek()[0] == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.next()[1]
            left = Bin(op, left, self.parse_mul())
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while self.peek() is not None and self.peek()[0] == 'OP' and self.peek()[1] in ('*', '/'):
            op = self.next()[1]
            left = Bin(op, left, self.parse_unary())
        return left

    def parse_unary(self):
        t = self.peek()
        if t is not None and t[1] in ('-',):
            self.next()
            return Unary('-', self.parse_unary())
        if t is not None and t[0] == 'NAME' and t[1].upper() == 'NOT':
            self.next()
            return Unary('NOT', self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        t = self.peek()
        if t is None:
            raise ValueError('表达式意外结束')
        if t[0] == 'NUM':
            self.next()
            return Num(float(t[1]))
        if t[0] == 'OP' and t[1] == '(':
            self.next()
            expr = self.parse_or()
            self.expect('OP', ')')
            return expr
        if t[0] == 'NAME':
            name = self.next()[1]
            if self.peek() is not None and self.peek()[1] == '(':
                self.next()
                args = []
                if self.peek() is not None and self.peek()[1] != ')':
                    while True:
                        args.append(self.parse_or())
                        if self.peek()[1] == ',':
                            self.next()
                            continue
                        break
                self.expect('OP', ')')
                return Call(name.upper(), args)
            return Var(name.upper())
        raise ValueError(f'意外 token: {t}')


# ---------------------------------------------------------------- 代码生成（TDX → hikyuu）

# 变量映射：TDX 行情变量 → hikyuu 表达式
VAR_MAP = {
    'OPEN': 'hku.OPEN()', 'HIGH': 'hku.HIGH()', 'LOW': 'hku.LOW()', 'CLOSE': 'hku.CLOSE()',
    'VOL': 'hku.VOL()', 'AMO': 'hku.AMO()',
    'O': 'hku.OPEN()', 'H': 'hku.HIGH()', 'L': 'hku.LOW()', 'C': 'hku.CLOSE()', 'V': 'hku.VOL()',
}

# 函数映射：TDX 函数 → 生成函数（参数为已翻译的 hikyuu 表达式列表）
FUNC_MAP = {
    'MA': lambda a: f'hku.MA({a[0]}, n={a[1]})',
    'EMA': lambda a: f'hku.EMA({a[0]}, n={a[1]})',
    'SMA': lambda a: f'hku.SMA({a[0]}, n={a[1]}, m={a[2]})',
    'REF': lambda a: f'hku.REF({a[0]}, n={a[1]})',
    'REFX': lambda a: f'hku.REFX({a[0]}, n={a[1]})',
    'CROSS': lambda a: f'hku.CROSS({a[0]}, {a[1]})',
    'LONGCROSS': lambda a: f'hku.LONGCROSS({a[0]}, {a[1]}, n={a[2]})',
    'EVERY': lambda a: f'hku.EVERY({a[0]}, n={a[1]})',
    'EXIST': lambda a: f'hku.EXIST({a[0]}, n={a[1]})',
    'COUNT': lambda a: f'hku.COUNT({a[0]}, n={a[1]})',
    'HHV': lambda a: f'hku.HHV({a[0]}, n={a[1]})',
    'LLV': lambda a: f'hku.LLV({a[0]}, n={a[1]})',
    'IF': lambda a: f'hku.IF({a[0]}, {a[1]}, {a[2]})',
    'ABS': lambda a: f'hku.ABS({a[0]})',
    'MAX': lambda a: f'hku.MAX({a[0]}, {a[1]})',
    'MIN': lambda a: f'hku.MIN({a[0]}, {a[1]})',
    'UPNDAY': lambda a: f'hku.UPNDAY({a[0]}, n={a[1]})',
    'DOWNNDAY': lambda a: f'hku.DOWNNDAY({a[0]}, n={a[1]})',
    'NDAY': lambda a: f'hku.NDAY({a[0]}, {a[1]}, n={a[2]})',
    'BARSLAST': lambda a: f'hku.BARSLAST({a[0]})',
    'SUM': lambda a: f'hku.SUM({a[0]}, n={a[1]})',
}

# 运算符映射：TDX → hikyuu（hikyuu Indicator 重载 & | ~）
OP_MAP = {
    'AND': lambda l, r: f'({l} & {r})',
    'OR': lambda l, r: f'({l} | {r})',
    '=': lambda l, r: f'({l} == {r})',
    '==': lambda l, r: f'({l} == {r})',
    '!=': lambda l, r: f'({l} != {r})',
    '>': lambda l, r: f'({l} > {r})',
    '<': lambda l, r: f'({l} < {r})',
    '>=': lambda l, r: f'({l} >= {r})',
    '<=': lambda l, r: f'({l} <= {r})',
    '+': lambda l, r: f'({l} + {r})',
    '-': lambda l, r: f'({l} - {r})',
    '*': lambda l, r: f'({l} * {r})',
    '/': lambda l, r: f'({l} / {r})',
}


def _fmt_num(v: float) -> str:
    """数字格式化：整数值不带小数点（TDX 惯例）。"""
    return str(int(v)) if v == int(v) else str(v)


def gen(node, params: dict) -> str:
    """AST → hikyuu Python 表达式（参数占位以变量名引用）。"""
    if isinstance(node, Num):
        return _fmt_num(node.value)
    if isinstance(node, Var):
        if node.name in VAR_MAP:
            return VAR_MAP[node.name]
        if node.name in params:
            return node.name.lower()
        raise ValueError(f'未定义的变量/函数: {node.name}')
    if isinstance(node, Call):
        args = [gen(a, params) for a in node.args]
        if node.name not in FUNC_MAP:
            raise ValueError(f'子集不支持的函数: {node.name}')
        return FUNC_MAP[node.name](args)
    if isinstance(node, Bin):
        l, r = gen(node.left, params), gen(node.right, params)
        if node.op in OP_MAP:
            return OP_MAP[node.op](l, r)
        raise ValueError(f'不支持的运算符: {node.op}')
    if isinstance(node, Unary):
        operand = gen(node.operand, params)
        if node.op == '-':
            return f'(-{operand})'
        if node.op == 'NOT':
            return f'(~{operand})'
    raise ValueError(f'未知 AST 节点: {node}')


def translate(text: str) -> dict:
    """完整翻译：TDX 公式文本 → {参数声明, hikyuu 表达式, 参数默认值}。

    参数定义语句（N:=10）提取为参数；最后一条表达式为输出（选股条件）。
    """
    stmts = Parser(text).parse()
    params: dict[str, float] = {}
    out_expr = None
    for name, expr in stmts:
        if name:
            # 参数声明：值必须是数字字面量
            if not isinstance(expr, Num):
                raise ValueError(f'参数 {name} 的默认值必须是数字')
            params[name] = expr.value
        else:
            out_expr = expr
    if out_expr is None:
        raise ValueError('公式缺少输出表达式')
    return {
        'params': params,
        'expr': gen(out_expr, params),
    }


# ---------------------------------------------------------------- 反向（hikyuu → TDX）

def gen_tdx_expr(node, params: dict) -> str:
    """AST → TDX 公式文本（与 gen 对称的反向生成）。"""
    if isinstance(node, Num):
        return _fmt_num(node.value)
    if isinstance(node, Var):
        if node.name in params:
            return node.name
        return node.name
    if isinstance(node, Call):
        return f'{node.name}({",".join(gen_tdx_expr(a, params) for a in node.args)})'
    if isinstance(node, Bin):
        op = '=' if node.op in ('=', '==') else node.op
        return f'({gen_tdx_expr(node.left, params)} {op} {gen_tdx_expr(node.right, params)})'
    if isinstance(node, Unary):
        op = 'NOT ' if node.op == 'NOT' else node.op
        return f'({op}{gen_tdx_expr(node.operand, params)})'
    raise ValueError(f'未知 AST 节点: {node}')


def to_tdx(text: str) -> str:
    """hikyuu 表达式（本翻译器生成的 TDX 公式文本）→ 规范化 TDX 文本。

    用途：翻译方向 2 的轻量方案——翻译器输出可再序列化回 TDX 文本，
    用于与原始公式对拍（往返一致性检验）。
    """
    stmts = Parser(text).parse()
    params = {n: e.value for n, e in stmts if n and isinstance(e, Num)}
    out = [e for n, e in stmts if not n]
    if not out:
        raise ValueError('公式缺少输出表达式')
    head = '\n'.join(f'{n}:={_fmt_num(v)};' for n, v in params.items())
    body = gen_tdx_expr(out[-1], params) + ';'
    return head + '\n' + body if head else body


if __name__ == '__main__':
    import hikyuu as hku
    import matplotlib

    matplotlib.use('Agg')
    import strategy_research.config as cfg_mod
    cfg_mod.init_hikyuu()

    samples = {
        'MA 金叉选股': 'CROSS(MA(CLOSE,10),MA(CLOSE,30))',
        '参数化 MA 金叉': 'N:=10;\nM:=30;\nCROSS(MA(CLOSE,N),MA(CLOSE,M))',
        '三日连涨': 'UPNDAY(CLOSE,3)',
        '量价条件': 'CLOSE>MA(CLOSE,20) AND VOL>REF(VOL,1)*1.5',
        '条件输出': 'IF(CROSS(MA(CLOSE,5),MA(CLOSE,20)),1,0)',
    }
    for title, text in samples.items():
        r = translate(text)
        print(f'== {title}')
        print(f'   源: {text}')
        print(f'   hikyuu: {r["expr"]}')
        print(f'   参数: {r["params"]}')
        print(f'   回译: {to_tdx(text)}')

    # 真实数据执行验证：MA 金叉公式在 sh000001 上的信号与第一闭环 SG_Cross 对比
    print('\n== 执行验证：翻译结果 vs 第一闭环 SG_Cross（sh000001） ==')
    import numpy as np
    from strategy_research.backtest import run_backtest

    result = run_backtest(skip_check=True, draw_charts=False)
    buy_dates = {t['datetime'][:10] for t in result.trades if t['business'] == '买入'}

    stk = hku.sm['sh000001']
    q = hku.Query(hku.Datetime(2020, 1, 2), hku.Datetime(2026, 8, 14), hku.Query.DAY,
                  recover_type=hku.Query.FORWARD)
    k = stk.get_kdata(q)
    t = translate('CROSS(MA(CLOSE,10),MA(CLOSE,30))')
    ns = {'hku': hku}
    cross = eval(t['expr'], ns)
    cross.set_context(k)
    dates = k.get_datetime_list()
    # 金叉信号在 bar i（收盘后），买入执行在 bar i+1 开盘（buy_delay），与第一闭环对齐
    trans_buys = {str(dates[i + 1].date()) for i in range(1, len(dates) - 1)
                  if cross[i] > 0 and cross[i - 1] <= 0}
    print(f'第一闭环买入日 {len(buy_dates)} 个，翻译公式金叉日 {len(trans_buys)} 个')
    print('一致:', buy_dates == trans_buys,
          '差异:', sorted(buy_dates ^ trans_buys)[:5])

    # UPNDAY 与客户端 UPN 公式对齐（公式验证链路的雏形：需 tq 批量调用，见 T4 方案）
    print('\n== UPNDAY 翻译 ==')
    t2 = translate('UPNDAY(CLOSE,3)')
    print('  ', t2['expr'])
    up = eval(t2['expr'], ns)
    up.set_context(k)
    print('  sh000001 最新值:', up[-1], '（0/1 语义与 UPN 一致）')
