#!python
# encoding: utf-8
# author: DifossChen
#
from difoss_stock_util.color_log_util import *
from difoss_stock_util.tdx_util import *
from difoss_stock_util.util import read_yaml_config
from pathlib import Path
import click



# -----------------------------------------------------------------------------------
@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.option('-l', '--level', default=1, help='显示第几级的所有行业')
def main(
    level: int
):
    if level < 1 or level > 3:
        raise ValueError("级别必须在1到3之间")

    I(**{k:v for k,v in locals().items() if v}, _level='PARAMETER')
    # 读取配置
    CFG = read_yaml_config()

    TDX_DIR = CFG.get('tdx', {}).get('base_dir', 'C:/new_tdx')
    T0002_DIR = Path(TDX_DIR, 'T0002')
    HQ_CACHE_DIR = Path(T0002_DIR, 'hq_cache')
    CLOUD_CFG_DIR = Path(T0002_DIR, 'cloud_cfg')

    # 读取行业xml
    hy_xml = CLOUD_CFG_DIR / 'hy_tree.xml'
    print(f"正在加载行业树文件: {hy_xml}")
    tree = TDXIndustryTree(xml_path=hy_xml)

    # 4. 显示所有一级行业
    print(f"\n1. 显示所有{level}级行业:")
    print("-" * 40)
    tree.display_level_industries(level=level)


if __name__ == "__main__":
    main()