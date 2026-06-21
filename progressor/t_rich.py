import time
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    SpinnerColumn,
    TaskID
)
from rich.console import Console
from rich.live import Live
from rich.table import Table
import random

console = Console()

def simulate_download():
    """模拟 pip install 风格的进度条"""
    
    with Progress(
        SpinnerColumn(),  # 左侧的旋转动画
        TextColumn("[progress.description]{task.description}"),  # 任务描述
        BarColumn(),  # 进度条
        "[progress.percentage]{task.percentage:>3.0f}%",  # 百分比
        DownloadColumn(),  # 下载大小显示
        TransferSpeedColumn(),  # 传输速度
        TimeRemainingColumn(),  # 剩余时间
        console=console,
        transient=True,  # 完成后隐藏进度条
    ) as progress:
        
        # 主任务
        task1 = progress.add_task(
            "[cyan]Downloading packages...", 
            total=1000,
            start=False
        )
        
        # 子任务（当前正在处理的文件）
        task2 = progress.add_task(
            "[yellow]Collecting numpy", 
            total=100,
            start=False
        )
        
        progress.start_task(task1)
        progress.start_task(task2)
        
        files = [
            "numpy-1.24.0-cp39-cp39-manylinux_2_17_x86_64.whl",
            "pandas-1.5.3-cp39-cp39-manylinux_2_17_x86_64.whl", 
            "requests-2.28.2-py3-none-any.whl",
            "rich-13.3.5-py3-none-any.whl"
        ]
        
        current_file_idx = 0
        
        while not progress.finished:
            # 更新主进度
            progress.update(task1, advance=random.uniform(0.5, 2))
            
            # 更新当前文件的进度
            progress.update(task2, advance=random.uniform(1, 5))
            
            # 如果当前文件完成，切换到下一个文件
            if progress.tasks[task2].completed >= 100:
                
                current_file_idx = (current_file_idx + 1) % len(files)
                progress.reset(
                    task2,
                    description=f"[yellow]Collecting {files[current_file_idx].split('-')[0]}",
                    total=100
                )
                progress.start_task(task2)
                
            if progress.tasks[task1].completed >= 100:
                progress.finished()
            
            time.sleep(0.05)

if __name__ == "__main__":
    simulate_download()