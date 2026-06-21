# -*- coding: utf-8 -*-
"""
Created on Mon Nov 10 02:20:12 2025

@author: DifossChen
"""
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, Text, Index, BigInteger
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import inspect
from datetime import datetime, timedelta
from difoss_stock_util import *

Base = declarative_base()

class InstrumentDetail(Base, TimestampMixin):
    __tablename__ = 'instrument_detail'
    
    # 主键和基础字段
    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    
    # 使用 BigInteger 存储 int64 时间戳
    Time = Column(BigIntegerDateTime, comment='时间戳', nullable=False, index=True)
    
    # 合约基础信息字段
    ExchangeID = Column(String(10), comment='合约市场代码')
    InstrumentID = Column(String(50), comment='合约代码')
    InstrumentName = Column(String(100), comment='合约名称')
    ProductID = Column(String(50), comment='合约的品种ID(期货)')
    ProductName = Column(String(100), comment='合约的品种名称(期货)')
    ProductType = Column(String(50), nullable=True, comment='产品类型')
    ExchangeCode = Column(String(50), comment='交易代码')
    UniCode = Column(String(50), comment='唯一（交易）代码')
    CreateDate = Column(String(8), comment='上市日期(期货)')
    OpenDate = Column(String(8), comment='IPO日期(股票)')
    ExpireDate = Column(Integer, comment='退市日或者到期日')
    TradingDay = Column(String(8), nullable=True, comment='交易日')
    PreClose = Column(Float, comment='前收盘价格')
    SettlementPrice = Column(Float, comment='前结算价格')
    UpStopPrice = Column(Float, comment='当日涨停价')
    DownStopPrice = Column(Float, comment='当日跌停价')
    FloatVolume = Column(Float, comment='流通股本')
    TotalVolume = Column(Float, comment='总股本')
    LongMarginRatio = Column(Float, comment='多头保证金率')
    ShortMarginRatio = Column(Float, comment='空头保证金率')
    PriceTick = Column(Float, comment='最小价格变动单位')
    VolumeMultiple = Column(Integer, comment='合约乘数(对期货以外的品种，默认是1)')
    MainContract = Column(Integer, comment='主力合约标记，1、2、3分别表示第一主力合约，第二主力合约，第三主力合约')
    LastVolume = Column(Integer, comment='昨日持仓量')
    InstrumentStatus = Column(Integer, comment='合约停牌状态，0：正常；1：停牌；-1：当日起复牌')
    IsTrading = Column(Boolean, comment='合约是否可交易')
    IsRecent = Column(Boolean, comment='是否是近月合约')
    ProductTradeQuota = Column(Float, comment='产品交易额度')
    ContractTradeQuota = Column(Float, comment='合约交易额度')
    ProductOpenInterestQuota = Column(Float, comment='产品持仓额度')
    ContractOpenInterestQuota = Column(Float, comment='合约持仓额度')
    
    # 时间戳字段
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    def __repr__(self):
        # return f"<InstrumentDetail(InstrumentID='{self.InstrumentID}', Time={self.Time}, InstrumentName='{self.InstrumentName}')>"
        time_str = TimeUtils.format_datetime(self.Time)
        return f"<InstrumentDetail(InstrumentID='{self.InstrumentID}', Time={time_str}, InstrumentName='{self.InstrumentName}')>"

# 创建复合索引（提高查询性能）
Index('idx_instrument_detail_code_time', InstrumentDetail.InstrumentID, InstrumentDetail.Time)  # 合约ID+时间 的 复合索引
Index('idx_instrument_detail_exchange_time', InstrumentDetail.ExchangeID, InstrumentDetail.Time)  # 交易所+时间索引
Index('idx_instrument_detail_time_status', InstrumentDetail.Time, InstrumentDetail.InstrumentStatus)  # 时间+状态索引
Index('idx_instrument_detail_main_contract_time', InstrumentDetail.MainContract, InstrumentDetail.Time)  # 主力合约+时间


class MarketData1D(Base, TimestampMixin):
    __tablename__ = 'market_data_1d'
    
    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True, comment='自增主键')
    
    # 基础行情字段
    Time = Column(BigIntegerDateTime, comment='时间戳', nullable=False, index=True)
    Open = Column(Float, comment='开盘价')
    High = Column(Float, comment='最高价')
    Low = Column(Float, comment='最低价')
    Close = Column(Float, comment='收盘价')
    Volume = Column(Float, comment='成交量')
    Amount = Column(Float, comment='成交额')
    SettlementPrice = Column(Float, comment='今结算')
    OpenInterest = Column(Float, comment='持仓量')
    PreClose = Column(Float, comment='前收价')
    SuspendFlag = Column(Integer, comment='停牌标记')
    
    # 扫雷宝分数
    SLB_Score = Column(Integer, comment='扫雷宝分数')
    
    # 关联字段（可根据需要添加）
    InstrumentID = Column(String(10), comment='合约代码')
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    def __repr__(self):
        return f"<MarketData1D(time='{self.Time}', close={self.Close}, volume={self.Volume})>"

# 创建索引（提高查询性能）
Index('idx_market_data_time', MarketData1D.Time)
Index('idx_market_data_instrument', MarketData1D.InstrumentID)
Index('idx_market_data_code_time', MarketData1D.InstrumentID, MarketData1D.Time)  # 合约ID+时间 的 复合索引
Index('idx_market_data_time_instrument', MarketData1D.Time, MarketData1D.InstrumentID)
Index('idx_market_data_slb_score', MarketData1D.SLB_Score)

def create_table():
    # 创建SQLite数据库连接
    engine = create_engine('sqlite:///stock.db', echo=True)
    
    # 创建表
    Base.metadata.create_all(engine)
    
    # 创建会话
    Session = sessionmaker(bind=engine)
    session = Session()
        
    
def create_tables_if_not_exist(engine):
    """创建表（如果表不存在）"""
    inspector = inspect(engine)
    
    tables_to_create = []
    
    # 检查 instrument_detail 表是否存在
    if not inspector.has_table('instrument_detail'):
        tables_to_create.append(InstrumentDetail.__table__)
        print("instrument_detail 表不存在，将创建")
    else:
        print("instrument_detail 表已存在")
    
    # 检查 market_data_1d 表是否存在
    if not inspector.has_table('market_data_1d'):
        tables_to_create.append(MarketData1D.__table__)
        print("market_data_1d 表不存在，将创建")
    else:
        print("market_data_1d 表已存在")
    
    # 创建不存在的表
    if tables_to_create:
        Base.metadata.create_all(engine, tables=tables_to_create)
        print("表创建完成")
    else:
        print("所有表都已存在，无需创建")

# 初始化数据库
def init_database(db_url='sqlite:///stock_data.db'):
    """初始化数据库"""
    engine = create_engine(db_url, echo=False)
    create_tables_if_not_exist(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session()

def add_market_data(data):
    """添加市场数据"""
    try:
        market_data = MarketData1D(**data)
        session.add(market_data)
        session.commit()
        print(f"成功添加市场数据: {data['time']}")
        return market_data
    except Exception as e:
        session.rollback()
        print(f"添加市场数据失败: {e}")
        return None

def batch_add_market_data(data_list):
    """批量添加市场数据"""
    try:
        market_data_list = [MarketData1D(**data) for data in data_list]
        session.bulk_save_objects(market_data_list)
        session.commit()
        print(f"成功批量添加 {len(data_list)} 条市场数据")
        return True
    except Exception as e:
        session.rollback()
        print(f"批量添加市场数据失败: {e}")
        return False


def get_market_data_from_xtdata():
    """从xtdata中获取市场数据
    """
    pass

def get_all_stock_code():
    """获取全市场所有股票代码
    """

# if __name__ == "__main__":
#     engine, session = init_database()
    
    
#     # 示例数据
#     sample_market_data = {
#         'time': '1750867200000',
#         'open': 27.80,
#         'high': 27.98,
#         'low': 27.54,
#         'close': 27.59,
#         'volume': 314808.0,
#         'amount': 8.716268e+08,
#         'settelementPrice': 0.0,
#         'openInterest': 15.0,
#         'preClose': 27.81,
#         'suspendFlag': 0,
#         'instrument_id': '002415'
#     }

#     # 添加示例数据
#     add_market_data(sample_market_data)

    # 初始化数据库
engine = create_engine('sqlite:///stock_data.db')  # financial_data.db
create_tables_if_not_exist(engine)
Session = sessionmaker(bind=engine)
session = Session()

# 示例1：直接使用 datetime 对象插入
def add_instrument_with_datetime():
    """使用 datetime 对象添加数据"""
    instrument_data = {
        'Time': datetime(2023, 12, 1, 9, 30, 0),  # 直接使用 datetime
        'ExchangeID': 'SZ',
        'InstrumentID': '002415',
        'InstrumentName': '海康威视',
        'PreClose': 31.5,
        'InstrumentStatus': 0,
        'IsTrading': True
    }
    
    instrument = InstrumentDetail(**instrument_data)
    session.add(instrument)
    session.commit()
    
    # 自动转换验证
    print(f"插入的 Time 值: {instrument.Time}")  # 毫秒时间戳
    print(f"转换为 datetime: {instrument.to_datetime()}")  # datetime 对象
    print(f"ISO 格式: {instrument.to_iso_format()}")

# 示例2：使用时间戳插入
def add_market_data_with_timestamp():
    """使用时间戳添加数据"""
    market_data = {
        'Time': TimeUtils.now_ms(),  # 使用工具类获取当前时间戳
        'Open': 27.80,
        'High': 27.98,
        'Low': 27.54,
        'Close': 27.59,
        'Volume': 314808,
        'InstrumentID': '002415'
    }
    
    md = MarketData1D(**market_data)
    session.add(md)
    session.commit()
    
    print(f"市场数据时间: {TimeUtils.format_datetime(md.Time)}")

# 示例3：查询和转换
def query_and_convert():
    """查询和时间转换示例"""
    # 查询今天的数据
    today_start = TimeUtils.today_start_ms()
    
    instruments = session.query(InstrumentDetail).filter(
        InstrumentDetail.Time >= today_start
    ).all()
    
    for inst in instruments:
        print(f"合约: {inst.InstrumentName}")
        print(f"  时间: {inst.to_iso_format()}")
        print(f"  日期: {inst.to_date_string()}")
    
    # 使用时间工具类进行复杂查询
    start_time = TimeUtils.date_to_ms('2023-12-01')
    end_time = TimeUtils.date_to_ms('2023-12-02')
    
    market_data = session.query(MarketData1D).filter(
        MarketData1D.Time.between(start_time, end_time)
    ).all()
    
    for md in market_data:
        print(f"市场数据: {TimeUtils.format_ms(md.Time)} - 收盘价: {md.close}")

# 示例4：批量操作
def batch_operations():
    """批量操作示例"""
    # 批量插入 instrument 数据
    instruments_batch = []
    base_time = datetime(2023, 12, 1, 9, 30, 0)
    
    for i in range(5):
        instrument_data = {
            'Time': base_time + timedelta(days=i),
            'ExchangeID': 'SZ',
            'InstrumentID': f'00000{i}',
            'InstrumentName': f'测试股票{i}',
            'PreClose': 10.0 + i,
            'InstrumentStatus': 0,
            'IsTrading': True
        }
        instruments_batch.append(InstrumentDetail(**instrument_data))
    
    session.bulk_save_objects(instruments_batch)
    session.commit()
    
    # 验证批量插入的数据
    for inst in instruments_batch:
        print(f"批量插入: {inst.InstrumentID} - {inst.to_iso_format()}")

# 示例5：时间比较和计算
def time_comparison():
    """时间比较示例"""
    # 获取两个时间点的数据
    time1 = TimeUtils.date_to_ms('2023-12-01')
    time2 = TimeUtils.date_to_ms('2023-12-02')
    
    inst1 = session.query(InstrumentDetail).filter_by(Time=time1).first()
    inst2 = session.query(InstrumentDetail).filter_by(Time=time2).first()
    
    if inst1 and inst2:
        print(f"是否同一天: {inst1.is_same_day(inst2)}")
        print(f"时间1: {inst1.to_iso_format()}")
        print(f"时间2: {inst2.to_iso_format()}")

if __name__ == "__main__":
    try:
        init_database()
        add_instrument_with_datetime()
        add_market_data_with_timestamp()
        query_and_convert()
        batch_operations()
        time_comparison()
    finally:
        session.close()