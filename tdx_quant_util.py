#!python

import pandas as pd
import pypinyin

import re


def convert_block_name_2_code(block_name: str) -> str:
    """
    将板块名称转换为板块代码

    Parameters:
    -----------
    block_name : str
        板块名称

    Returns:
    --------
    str
        板块代码
        
    Rules:
    - 汉字转换为拼音首字母大写
    - 数字、下划线“_”、中划线“-”、点“.”和 波浪线“~” 保留
    - 其他字符删除
    """
    converted = ''.join([
        pypinyin.pinyin(c, style=pypinyin.NORMAL)[0][0][0].upper()
        if ('\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
        else c if c.isdigit() or c in ['_', '-', '.', '~']
        else ''
        for c in block_name
    ])
    return converted
