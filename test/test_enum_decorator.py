#! python
# -*- coding: utf-8 -*-

# metadata_enum.py
from enum import Enum, EnumType
from typing import ClassVar, Optional, Union, Any
from functools import lru_cache
import sys
from rich import print as pprint


class MetadataEnumType(EnumType):
    """
    支持元数据的枚举元类
    参考 EnumType 的设计模式
    """
    
    @classmethod
    def __prepare__(metacls, cls, bases, **kwds):
        # 创建命名空间字典
        enum_dict = super().__prepare__(cls, bases, **kwds)
        return enum_dict
    
    def __new__(metacls, cls, bases, classdict, **kwds):
        # 先创建枚举类
        enum_class = super().__new__(metacls, cls, bases, classdict, **kwds)
        
        # 检查是否有 METADATA 定义（不使用下划线）
        if 'METADATA' in classdict:
            metadata = classdict['METADATA']
            
            # 构建各种映射字典
            enum_class._int_to_enum = {}
            enum_class._enum_to_int = {}
            enum_class._enum_to_chinese = {}
            enum_class._str_to_enum = {}
            enum_class._chinese_to_enum = {}
            
            # 收集所有枚举成员
            members = {}
            for name in dir(enum_class):
                attr = getattr(enum_class, name)
                if isinstance(attr, enum_class):
                    members[name] = attr
            
            # 处理元数据
            for item in metadata:
                if len(item) == 4:
                    enum_name, str_val, int_val, chinese_name = item
                    
                    enum_member = members.get(enum_name)
                    if enum_member:
                        if int_val is not None:
                            enum_class._int_to_enum[int_val] = enum_member
                            enum_class._enum_to_int[enum_member] = int_val
                        if chinese_name:
                            enum_class._enum_to_chinese[enum_member] = chinese_name
                            enum_class._chinese_to_enum[chinese_name] = enum_member
                        if str_val is not None and str_val != '':
                            enum_class._str_to_enum[str_val] = enum_member
        
        return enum_class
    
    def __call__(cls, value, *args, **kwds):
        """
        重写 __call__ 方法来处理各种类型的值
        """
        # 如果 value 已经是枚举成员，直接返回
        if isinstance(value, cls):
            return value
            
        # 处理 None
        if value is None:
            value = ''
            
        # 处理字符串
        if isinstance(value, str):
            # 如果是数字字符串，尝试转整数
            if value.isdigit():
                try:
                    int_val = int(value)
                    if int_val in cls._int_to_enum:
                        return cls._int_to_enum[int_val]
                except ValueError:
                    pass
            # 尝试从字符串值查找
            if hasattr(cls, '_str_to_enum') and value in cls._str_to_enum:
                return cls._str_to_enum[value]
        
        # 处理整数
        if isinstance(value, int):
            if hasattr(cls, '_int_to_enum') and value in cls._int_to_enum:
                return cls._int_to_enum[value]
        
        # 调用父类的 __call__ 处理其他情况
        return super().__call__(value, *args, **kwds)
    
    def __init__(cls, clsname, bases, classdict, **kwds):
        super().__init__(clsname, bases, classdict, **kwds)
        
        # 只有在有映射字典时才添加额外的方法
        if hasattr(cls, '_int_to_enum'):
            # 添加属性方法
            @property
            def str_value(self):
                """获取字符串值"""
                return next(
                    (s for s, e in self.__class__._str_to_enum.items() if e == self),
                    ''
                )
            cls.str_value = str_value
            
            @property
            def int_value(self):
                """获取整数值"""
                return self.__class__._enum_to_int.get(self, -1)
            cls.int_value = int_value
            
            @property
            def chinese_name(self):
                """获取中文名称"""
                return self.__class__._enum_to_chinese.get(self, '')
            cls.chinese_name = chinese_name
            
            @classmethod
            def from_int(cls, value):
                """从整数值获取枚举成员"""
                if isinstance(value, Enum):
                    value = value.value
                return cls._int_to_enum.get(value)
            cls.from_int = classmethod(from_int)
            
            @classmethod
            def from_str(cls, value):
                """从字符串值获取枚举成员"""
                return cls._str_to_enum.get(value)
            cls.from_str = classmethod(from_str)
            
            @classmethod
            def chinese_name_2_en(cls, chinese_name):
                """中文名称→枚举值的字符串值"""
                enum_member = cls._chinese_to_enum.get(chinese_name)
                if enum_member:
                    return next(
                        (s for s, e in cls._str_to_enum.items() if e == enum_member),
                        None
                    )
                return None
            cls.chinese_name_2_en = classmethod(chinese_name_2_en)
            
            @classmethod
            @lru_cache(maxsize=1)
            def allows(cls):
                """获取允许的字符串值列表"""
                return list(cls._str_to_enum.keys())
            cls.allows = classmethod(allows)
            
            @classmethod
            @lru_cache(maxsize=1)
            def allows_cn(cls):
                """获取允许的中文名称列表"""
                return [name for name in cls._chinese_to_enum.keys() if name]
            cls.allows_cn = classmethod(allows_cn)
            
            def __str__(self):
                """字符串表示返回字符串值"""
                return self.str_value
            cls.__str__ = __str__
            
            def __repr__(self):
                """更友好的表示"""
                return f"<{self.__class__.__name__}.{self.name}: str='{self.str_value}', int={self.int_value}, cn='{self.chinese_name}'>"
            cls.__repr__ = __repr__

class MetadataEnum(Enum, metaclass=MetadataEnumType):
    """
    支持元数据的枚举基类
    
    使用示例：
        class MyEnum(MetadataEnum):
            METADATA = [
                ('MEMBER_NAME', 'str_value', int_value, '中文名称'),
                ...
            ]
            
            MEMBER_NAME = 'str_value'
    """
    pass

# 使用新基类重新定义三个枚举
class DividendType(MetadataEnum):
    """复权类型"""
    METADATA = [
        ('UNADJUSTED', 'none', 0, '不复权'),
        ('FORWARD_ADJUSTED', 'front', 1, '前复权'),
        ('BACKWARD_ADJUSTED', 'back', 2, '后复权'),
    ]
    
    UNADJUSTED = 'none'
    FORWARD_ADJUSTED = 'front'
    BACKWARD_ADJUSTED = 'back'

class SecurityType(MetadataEnum):
    """证券类型"""
    METADATA = [
        ('STOCK', 'stock', 1, '股票'),
        ('STOCK_B', 'stock_b', 2, 'B股'),
        ('FUND', 'fund', 3, '基金'),
        ('BOND', 'bond', 4, '债券'),
        ('INDEX', 'index', 5, '指数'),
        ('TDX_INDEX', 'tdx_index', 6, '通达信指数'),
        ('OPTION', 'option', 7, '期权'),
        ('FUTURES', 'futures', 8, '期货'),
        ('WARRANT', 'warrant', 9, '权证'),
        ('REPO', 'repo', 10, '回购'),
        ('OTHER', 'other', 99, '其他'),
    ]
    
    STOCK = "stock"
    STOCK_B = "stock_b"
    FUND = "fund"
    BOND = "bond"
    INDEX = "index"
    TDX_INDEX = "tdx_index"
    OPTION = "option"
    FUTURES = "futures"
    WARRANT = "warrant"
    REPO = "repo"
    OTHER = "other"

class MarketType(MetadataEnum):
    """市场类型"""
    METADATA = [
        ('NULL', '', -1, ''),
        ('SZ', 'SZ', 0, '深圳交易所'),
        ('SH', 'SH', 1, '上海交易所'),
        ('BJ', 'BJ', 2, '北京交易所'),
        ('NQ', 'NQ', 44, '新三板'),
        ('SHO', 'SHO', 8, '上海个股期权'),
        ('SZO', 'SZO', 9, '深证个股期权'),
        ('HK', 'HK', 31, '港股个股'),
        ('US', 'US', 74, '美国股票'),
        ('CSI', 'CSI', 62, '中证指数'),
        ('CNI', 'CNI', 102, '国证指数'),
        ('HG', 'HG', 38, '国内宏观指标'),
        ('CFF', 'CFF', 47, '中金期货'),
        ('CZC', 'CZC', 28, '郑州期货'),
        ('DCE', 'DCE', 29, '大连期货'),
        ('SHF', 'SHF', 30, '上海期货'),
        ('GFE', 'GFE', 66, '广州期货'),
        ('INE', 'INE', 30, '上海能源'),
        ('HI', 'HI', 27, '港股指数'),
    ]
    
    NULL = ''
    SZ = 'SZ'
    SH = 'SH'
    BJ = 'BJ'
    NQ = 'NQ'
    SHO = 'SHO'
    SZO = 'SZO'
    HK = 'HK'
    US = 'US'
    CSI = 'CSI'
    CNI = 'CNI'
    HG = 'HG'
    CFF = 'CFF'
    CZC = 'CZC'
    DCE = 'DCE'
    SHF = 'SHF'
    GFE = 'GFE'
    INE = 'INE'
    HI = 'HI'
    
    # @classmethod
    # @lru_cache(maxsize=1)
    # def allows(cls) -> list[str]:
    #     """覆盖默认实现，只返回部分市场"""
    #     return ['SH', 'SZ', 'BJ', 'SZO', 'HK']

# 测试代码
if __name__ == "__main__":
    from rich.console import Console
    CONSOLE = Console()

    try:

        print("=" * 50)
        print("测试 DividendType")
        print("=" * 50)
        print(f"DividendType.UNADJUSTED: {DividendType.UNADJUSTED}")
        print(f"str_value: {DividendType.UNADJUSTED.str_value}")
        print(f"int_value: {DividendType.UNADJUSTED.int_value}")
        print(f"chinese_name: {DividendType.UNADJUSTED.chinese_name}")
        print(f"repr: {repr(DividendType.UNADJUSTED)}")
        print(f"from_str('front'): {DividendType.from_str('front')}")
        print(f"from_int(0): {DividendType.from_int(0)}")
        print(f"chinese_name_2_en('前复权'): {DividendType.chinese_name_2_en('前复权')}")
        print(f"allows(): {DividendType.allows()}")
        print(f"allows_cn(): {DividendType.allows_cn()}")

        print("\n" + "=" * 50)
        print("测试 SecurityType")
        print("=" * 50)
        print(f"SecurityType.STOCK: {SecurityType.STOCK}")
        print(f"str_value: {SecurityType.STOCK.str_value}")
        print(f"int_value: {SecurityType.STOCK.int_value}")
        print(f"chinese_name: {SecurityType.STOCK.chinese_name}")
        print(f"repr: {repr(SecurityType.STOCK)}")
        print(f"from_str('bond'): {SecurityType.from_str('bond')}")
        print(f"from_int(1): {SecurityType.from_int(1)}")
        print(f"chinese_name_2_en('股票'): {SecurityType.chinese_name_2_en('股票')}")
        print(f"allows(): {SecurityType.allows()}")
        print(f"allows_cn(): {SecurityType.allows_cn()}")

        print("\n" + "=" * 50)
        print("测试 MarketType")
        print("=" * 50)
        print(f"MarketType.SH: {MarketType.SH}")
        print(f"str_value: {MarketType.SH.str_value}")
        print(f"int_value: {MarketType.SH.int_value}")
        print(f"chinese_name: {MarketType.SH.chinese_name}")
        print(f"repr: {repr(MarketType.SH)}")
        print(f"from_str('SZ'): {MarketType.from_str('SZ')}")
        print(f"from_int(1): {MarketType.from_int(1)}")
        print(f"chinese_name_2_en('深圳交易所'): {MarketType.chinese_name_2_en('深圳交易所')}")
        print(f"allows(): {MarketType.allows()}")
        print(f"allows_cn(): {MarketType.allows_cn()}")

        # 测试初始化
        print("\n" + "=" * 50)
        print("测试初始化")
        print("=" * 50)
        print(f"MarketType('SH'): {MarketType('SH')}")
        print(f"MarketType(1): {MarketType(1)}")
        print(f"MarketType(MarketType.SZ): {MarketType(MarketType.SZ)}")

        # 测试Python 3.12特定的枚举特性
        print("\n" + "=" * 50)
        print("测试Python 3.12特性")
        print("=" * 50)
        print(f"成员列表: {list(MarketType)}")
        print(f"名称访问: {MarketType['SH']}")
        print(f"值访问: {MarketType('SH')}")

    except:
        CONSOLE.print_exception(show_locals=True)