# 域文档

工程技能在探索代码库时应如何消费本仓库的域文档。

## 探索前先读这些

- 仓库根目录的 **`CONTEXT.md`**,或
- 若存在 **`CONTEXT-MAP.md`**(指向每个上下文各自的 `CONTEXT.md`,逐个读取与主题相关的)
- **`docs/adr/`** —— 读取与你即将工作的区域相关的 ADR。多上下文仓库还要检查 `src/<context>/docs/adr/` 的上下文级决策。

这些文件不存在时,**静默继续**。不标记缺失;不要主动建议创建。`/domain-modeling` 技能(通过 `/grill-with-docs` 和 `/improve-codebase-architecture` 触达)会在术语或决策真正落地时惰性创建它们。

## 文件结构

单上下文仓库(大多数仓库):

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

多上下文仓库(根目录存在 `CONTEXT-MAP.md`):

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← 全局决策
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← 上下文专属决策
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用词汇表里的术语

当你的输出命名一个域概念(issue 标题、重构提案、假设、测试名)时,使用 `CONTEXT.md` 中定义的术语。不要漂移到词汇表明确回避的同义词。

如果需要的概念不在词汇表里,那是个信号 —— 要么你在发明项目没用的语言(重新考虑),要么有真实缺口(记下来交给 `/domain-modeling`)。

## 标记 ADR 冲突

如果你的输出与现有 ADR 矛盾,明确浮出而不是静默覆盖:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
