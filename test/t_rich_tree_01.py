#!python
# encoding: utf-8
# author: DifossChen
#
from rich.tree import Tree
from rich import print

# 创建树
tree = Tree("📁 项目根目录", guide_style="bold bright_blue")

# 添加带样式的节点
python_node = tree.add("🐍 Python 代码", style="green")
python_node.add("[link=./src/main.py]main.py[/link]")
python_node.add("[link=./src/utils.py]utils.py[/link]")

data_node = tree.add("📊 数据文件", style="yellow")
data_node.add("[link=./data/raw.csv]raw.csv[/link]")
data_node.add("[link=./data/processed.parquet]processed.parquet[/link]")

docs_node = tree.add("📚 文档", style="cyan")
docs_node.add("[link=./docs/README.md]README.md[/link]")

# 打印树（支持鼠标点击链接）
print(tree)
