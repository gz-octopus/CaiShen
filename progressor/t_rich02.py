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
from rich.layout import Layout

console = Console()

class PipStyleProgress:
    """pip 风格进度显示"""
    
    def __init__(self):
        # 创建进度对象但不启动 Live
        self.progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold cyan]{task.description}"),
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
        
        self.live = None  # 稍后初始化
        self.main_task_id = None
        self.sub_task_id = None
        self.current_file = ""
        
    def __enter__(self):
        """上下文管理器入口"""
        self.live = Live(
            self.progress,
            console=console,
            refresh_per_second=20,
            screen=False,
            transient=False,  # 完成后不自动清除
        )
        self.live.__enter__()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if self.live:
            self.live.__exit__(exc_type, exc_val, exc_tb)
    
    def start_download(self, total_bytes: int):
        """开始下载"""
        self.main_task_id = self.progress.add_task(
            "[bold]Downloading packages",
            total=total_bytes,
            visible=True
        )
    
    def update_file_progress(self, filename: str, current: int, total: int, doing: str = 'Downloading'):
        """更新文件下载进度"""
        # 如果文件改变，更新描述而不是创建新任务
        if filename != self.current_file:
            self.current_file = filename
            if self.sub_task_id is not None:
                # 更新现有任务
                self.progress.reset(
                    self.sub_task_id,
                    description=f"[dim]{doing} {filename}",
                    total=total,
                    completed=0
                )
            else:
                # 创建新任务
                self.sub_task_id = self.progress.add_task(
                    f"[dim]{doing} {filename}",
                    total=total
                )
        
        # 更新进度
        if self.sub_task_id is not None:
            self.progress.update(
                self.sub_task_id,
                completed=current,
                description=f"[dim]{doing} {filename}"
            )
    
    def update_main_progress(self, completed: int):
        """更新主进度"""
        if self.main_task_id is not None:
            self.progress.update(
                self.main_task_id,
                completed=completed
            )
    
    def complete_current_file(self):
        """标记当前文件完成"""
        if self.sub_task_id is not None:
            task = self.progress.tasks[self.sub_task_id]
            self.progress.update(
                self.sub_task_id,
                completed=task.total,
                description=f"[green]✓ {self.current_file}"
            )
    
    def finish(self, message: str = "Successfully installed!", what: str = 'Download'):
        """完成所有操作"""
        # 确保所有任务完成
        if self.main_task_id is not None:
            task = self.progress.tasks[self.main_task_id]
            self.progress.update(
                self.main_task_id,
                completed=task.total,
                description=f"[bold green]✓ {what} complete"
            )
        
        console.print(f"\n[bold green]{message}")

def safe_simulate_pip_install():
    """安全地模拟 pip install 过程"""
    
    packages = [
        ("numpy", "1.24.0", 15_200_000),
        ("pandas", "1.5.3", 28_500_000),
        ("matplotlib", "3.7.0", 12_300_000),
    ]
    
    try:
        with PipStyleProgress() as progress:
            total_size = sum(size for _, _, size in packages)
            progress.start_download(total_size)
            
            downloaded_total = 0
            
            for package, version, size in packages:
                filename = f"{package}-{version}-py3-none-any.whl"
                
                console.print(f"\n[bold blue]Collecting {package}=={version}")
                
                # 模拟文件下载
                chunk_size = 1024 * 1024  # 1MB chunks
                downloaded_file = 0
                
                while downloaded_file < size:
                    # 模拟下载块
                    chunk = min(chunk_size, size - downloaded_file)
                    downloaded_file += chunk
                    downloaded_total += chunk
                    
                    # 更新进度
                    progress.update_main_progress(downloaded_total)
                    progress.update_file_progress(
                        filename, 
                        downloaded_file, 
                        size
                    )
                    
                    # 添加随机延迟模拟网络
                    delay = random.uniform(0.05, 0.15)
                    time.sleep(delay)
                
                # 文件下载完成
                progress.complete_current_file()
                console.print(f"  [green]Downloaded {filename}")
                
                # 模拟解压安装
                console.print(f"  [yellow]Installing {package}...")
                time.sleep(0.5)
            
            # 全部完成
            progress.finish("✓ Successfully installed all packages!")
            
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠ Installation interrupted by user")
    except Exception as e:
        console.print(f"\n[red]✗ Error during installation: {e}")
    finally:
        console.print("[dim]Cleanup completed")

# # 测试函数
# def test_progress_stability():
#     """测试进度条的稳定性"""
    
#     def simulate_single_download():
#         """模拟单个下载任务"""
#         total = 10_000_000
#         downloaded = 0
#         chunk_size = 100_000
        
#         while downloaded < total:
#             chunk = min(chunk_size, total - downloaded)
#             downloaded += chunk
#             yield downloaded, total
    
#     try:
#         with PipStyleProgress() as progress:
#             progress.start_download(10_000_000)
            
#             # 模拟多个文件
#             files = [
#                 "package1-1.0.0.whl",
#                 "package2-2.0.0.whl", 
#                 "package3-3.0.0.whl"
#             ]
            
#             for i, filename in enumerate(files, 1):
#                 console.print(f"\n[bold]Processing file {i}/3: {filename}")
                
#                 # 重置文件进度
#                 progress.current_file = filename
#                 if progress.sub_task_id is not None:
#                     progress.progress.reset(
#                         progress.sub_task_id,
#                         description=f"[dim]Processing {filename}",
#                         total=10_000_000,
#                         completed=0
#                     )
                
#                 # 模拟下载
#                 for current, total in simulate_single_download():
#                     progress.update_main_progress(current)
#                     progress.update_file_progress(filename, current, total)
#                     time.sleep(0.01)
                
#                 progress.complete_current_file()
            
#             progress.finish("✓ All files processed successfully!")
            
#     except Exception as e:
#         console.print(f"[red]Test failed: {e}")
#         import traceback
#         traceback.print_exc()

if __name__ == "__main__":
    # 运行稳定版本
    print("Running stable version...")
    safe_simulate_pip_install()
    
    # 或者运行测试
    # test_progress_stability()