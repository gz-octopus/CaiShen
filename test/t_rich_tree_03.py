#!python
# encoding: utf-8
# author: DifossChen
#
from rich.tree import Tree
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.console import Console
import time

class TreeBrowser:
    """交互式树状浏览器"""
    
    def __init__(self):
        self.console = Console()
        self.tree = self.create_tree()
        self.selected_node = None
        
    def create_tree(self):
        """创建文件系统树"""
        tree = Tree(
            "[reverse]📁 文件浏览器[/reverse]",
            guide_style="bright_blue",
            expanded=True
        )
        
        # 用户目录
        home = tree.add("🏠 [bold cyan]用户目录[/bold cyan]", expanded=True)
        home.add("📄 [link=file:///home/user/docs/resume.pdf]简历.pdf[/link]")
        home.add("📄 [link=file:///home/user/docs/notes.txt]笔记.txt[/link]")
        
        # 项目目录
        projects = home.add("📁 [bold green]项目[/bold green]", expanded=True)
        
        web_project = projects.add("🌐 [link=file:///home/user/projects/web]网站项目[/link]", expanded=False)
        web_project.add("📄 index.html")
        web_project.add("📄 style.css")
        web_project.add("📄 app.js")
        
        data_project = projects.add("📊 [link=file:///home/user/projects/data]数据分析[/link]", expanded=True)
        data_project.add("📄 analysis.ipynb")
        data_project.add("📄 dataset.csv")
        
        # 媒体文件
        media = home.add("🎵 [bold magenta]媒体[/bold magenta]", expanded=False)
        media.add("🎵 music.mp3")
        media.add("🎬 video.mp4")
        media.add("🖼️ photo.jpg")
        
        return tree
    
    def display(self):
        """显示树状浏览器"""
        panel = Panel(
            self.tree,
            title="[bold yellow]文件浏览器[/bold yellow]",
            subtitle="[dim]点击链接打开文件 • 展开/折叠节点[/dim]",
            border_style="bright_blue"
        )
        
        self.console.print(panel)
        self.console.print("\n[dim]提示:[/dim]")
        self.console.print("  • 点击文件链接打开文件")
        self.console.print("  • 使用鼠标点击节点展开/折叠")
        self.console.print("  • 按 Ctrl+C 退出")

# 运行浏览器
browser = TreeBrowser()
browser.display()
