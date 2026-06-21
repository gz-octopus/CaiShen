import os

from difoss_stock_util.util import read_yaml_config
from difoss_stock_util.color_log_util import *

# 设置环境变量
CFG=read_yaml_config()

T(CFG=CFG, _level='CONFIG', _indent=2)
