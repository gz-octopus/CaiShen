#!python
# encoding: utf-8
# author: DifossChen
#
from rich.tree import Tree
from rich import print

def create_project_tree():
    """创建可折叠的项目树"""
    tree = Tree(
        "[bold magenta]📦 我的项目[/bold magenta]",
        guide_style="bright_blue",
        expanded=True  # 初始展开
    )
    
    # 源代码目录（可折叠）
    src = tree.add("[bold green]📁 src/[/bold green]", guide_style="green")
    src.add("[link=file://./src/__init__.py]__init__.py[/link]")
    src.add("[link=file://./src/main.py]main.py[/link]")
    src.add("[link=file://./src/utils.py]utils.py[/link]")
    
    # 测试目录（初始折叠）
    tests = tree.add("[bold yellow]📁 tests/[/bold yellow]", expanded=False)
    tests.add("[link=file://./tests/test_main.py]test_main.py[/link]")
    tests.add("[link=file://./tests/test_utils.py]test_utils.py[/link]")
    
    # 配置文件（可折叠）
    config = tree.add("[bold cyan]📁 config/[/bold cyan]", expanded=True)
    config.add("[link=file://./config/settings.yaml]settings.yaml[/link]")
    config.add("[link=file://./config/secrets.env]secrets.env[/link]")
    
    # 数据目录（多层嵌套）
    data = tree.add("[bold red]📁 data/[/bold red]", expanded=True)
    raw_data = data.add("[dim]📁 raw/[/dim]", expanded=False)
    raw_data.add("2024-01.csv")
    raw_data.add("2024-02.csv")
    
    processed_data = data.add("[dim]📁 processed/[/dim]", expanded=True)
    processed_data.add("cleaned.parquet")
    processed_data.add("aggregated.feather")
    
    return tree

# 打印可折叠树
print(create_project_tree())