import time
import random
from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
    SpinnerColumn,
    TaskProgressColumn,
)
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from difoss_stock_util.color_log_util import *

console = Console()

class PipLikeProgress:
    """模拟 pip install 风格的进度显示"""
    
    def __init__(self):
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
            console=console,
            expand=True,
        )
        
        self.live = Live(
            self._get_layout(),
            console=console,
            refresh_per_second=10,
            screen=False
        )
        
        self.main_task = None
        self.sub_task = None
        self.current_file = None
        
    def _get_layout(self):
        """创建布局"""
        return self.progress
    
    def start(self, total_size: int):
        """开始下载"""
        self.live.start()
        self.main_task = self.progress.add_task(
            "[bold cyan]Downloading packages",
            total=total_size,
            visible=True
        )
    
    def update_current_file(self, filename: str, current: int, total: int):
        """更新当前正在处理的文件"""
        # 如果子任务不存在或文件变化，创建新任务
        if self.sub_task is None or self.current_file != filename:
            if self.sub_task is not None:
                self.progress.remove_task(self.sub_task)
            
            self.current_file = filename
            self.sub_task = self.progress.add_task(
                f"[yellow]  ├─ {filename}",
                total=total,
                start=False
            )
            self.progress.start_task(self.sub_task)
        
        # 更新进度
        self.progress.update(self.sub_task, completed=current)
    
    def update_main_progress(self, completed: int):
        """更新主进度"""
        if self.main_task is not None:
            self.progress.update(self.main_task, completed=completed)
    
    def complete_file(self):
        """完成当前文件"""
        if self.sub_task is not None:
            self.progress.update(self.sub_task, completed=self.progress.tasks[self.sub_task].total)
            self.progress.stop_task(self.sub_task)
    
    def finish(self):
        """完成所有下载"""
        if self.main_task is not None:
            self.progress.update(self.main_task, completed=self.progress.tasks[self.main_task].total)
        self.live.stop()
        console.print("[bold green]✓ Successfully installed!")

def simulate_pip_install():
    """模拟 pip install 过程"""
    
    packages = [
        ("numpy", "1.24.0", 15200000),
        ("pandas", "1.5.3", 28500000),
        ("matplotlib", "3.7.0", 12300000),
        ("requests", "2.28.2", 8500000),
        ("rich", "13.3.5", 3200000),
    ]
    
    progress = PipLikeProgress()
    
    total_size = sum(size for _, _, size in packages)
    progress.start(total_size)
    
    downloaded = 0
    
    for package, version, size in packages:
        filename = f"{package}-{version}-py3-none-any.whl"
        
        # 模拟下载文件
        chunk_size = 1024 * 512  # 512KB 块
        downloaded_in_file = 0
        
        console.print(f"\n[bold]Collecting {package}=={version}[/bold]")
        
        while downloaded_in_file < size:
            # 模拟下载块
            chunk = min(chunk_size, size - downloaded_in_file)
            downloaded_in_file += chunk
            downloaded += chunk
            
            # 更新进度
            progress.update_main_progress(downloaded)
            progress.update_current_file(
                filename, 
                downloaded_in_file, 
                size
            )
            
            # 模拟网络波动
            time.sleep(random.uniform(0.05, 0.2))
            I(downloaded_in_file=downloaded_in_file)
        
        progress.complete_file()
        console.print(f"[green]  Downloaded {package}-{version}")
    
    progress.finish()

if __name__ == "__main__":
    simulate_pip_install()