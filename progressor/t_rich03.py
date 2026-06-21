import time
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.console import Console

console = Console()

def simple_stable_progress():
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
        refresh_per_second=10,
    ) as progress:
        
        main_task = progress.add_task("[cyan]Installing...", total=100)
        
        # 模拟步骤
        steps = [
            ("Collecting metadata", 10),
            ("Resolving dependencies", 20),
            ("Downloading packages", 50),
            ("Installing", 15),
            ("Cleaning up", 5),
        ]
        
        for description, duration in steps:
            progress.update(main_task, description=f"[cyan]{description}")
            for _ in range(duration):
                progress.advance(main_task)
                time.sleep(0.05)
        
        console.print("\n[bold green]✓ Installation successful!")

if __name__ == "__main__":
    simple_stable_progress()