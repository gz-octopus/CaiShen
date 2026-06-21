
from difoss_stock_util import *
from difoss_stock_util.color_log_util import *
from pathlib import Path 
import click
from datetime import datetime

belong_trading_date = calc_belong_trading_day(datetime.now())
default_output_dir = f'SLB-{belong_trading_date.strftime("%Y%m%d")}'

@click.command()
@click.option('-i', '--input-dir', required=False, default=default_output_dir,
              help="扫雷宝数据文件夹")
def rename_filename(input_dir):
    """把旧的 SLB.{stock.short_code}.json 文件更名为 SLB.{stock.full_code}.json
    """
    D(**locals())

    mgr = SLBFileManager(input_dir)
    
    I(总共有扫雷宝文件_个=mgr.count_files())
    files = mgr.list_all_files()
    
    i = 0
    for file in files:
        fn = file['filename']
        new_fn = f"SLB.{file['full_code']}.json"
        if fn and str(fn).count('.') == 2: # 旧版本使用 short_code，所以少一个"."
            I("✅ 改名", old_name=fn, rename_to=new_fn, file_info=file)
            os.rename(os.path.join(input_dir, fn), os.path.join(input_dir, new_fn))
        else:
            D("文件名已是最新版本，无需更名", file=fn)


if __name__ == "__main__":
    rename_filename()