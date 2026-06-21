#!/usr/bin/env python3
# encoding: utf-8
"""
SQLAlchemy 连接 TDengine 数据库操作示例
需要安装: pip install sqlalchemy taospy
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建基类
Base = declarative_base()

class SensorData(Base):
    """传感器数据表模型"""
    __tablename__ = 'sensor_data'
    
    # TDengine 推荐使用 ts 作为时间戳主键
    ts = Column(DateTime, primary_key=True)
    device_id = Column(String(50), nullable=False)
    temperature = Column(Float)
    humidity = Column(Float)
    location = Column(String(100))
    
    def __repr__(self):
        return f"<SensorData(ts={self.ts}, device_id='{self.device_id}', temp={self.temperature})>"

def init_database():
    """初始化数据库连接和表结构"""
    # TDengine 连接字符串格式
    # 原生连接: taos://username:password@host:port/database
    # WebSocket连接: taosws://username:password@host:port/database
    
    # 使用 WebSocket 连接（推荐）
    database_url = "taosws://root:taosdata@localhost:6041/test"
    
    # 创建引擎
    engine = create_engine(database_url, echo=True)
    
    # 创建会话工厂
    SessionLocal = sessionmaker(bind=engine)
    
    # 创建数据库表
    try:
        Base.metadata.create_all(engine)
        logger.info("数据库表创建成功")
    except Exception as e:
        logger.error(f"创建表失败: {e}")
        # 如果数据库不存在，先创建数据库
        with engine.connect() as conn:
            conn.execute(text("CREATE DATABASE IF NOT EXISTS test_db"))
            conn.commit()
        Base.metadata.create_all(engine)
        logger.info("数据库和表创建成功")
    
    return engine, SessionLocal

def demo_crud_operations():
    """演示 CRUD 操作"""
    engine, SessionLocal = init_database()
    session = SessionLocal()
    
    try:
        # 1. 插入数据（Create）
        logger.info("=== 插入数据 ===")
        current_time = datetime.now()
        
        sensor_data_list = [
            SensorData(
                ts=current_time,
                device_id="device_001",
                temperature=25.6,
                humidity=65.2,
                location="Room A"
            ),
            SensorData(
                ts=datetime(2024, 11, 9, 16, 30, 0),
                device_id="device_002",
                temperature=23.8,
                humidity=62.7,
                location="Room B"
            ),
            SensorData(
                ts=datetime(2024, 11, 9, 16, 35, 0),
                device_id="device_003",
                temperature=26.1,
                humidity=63.9,
                location="Room C"
            )
        ]
        
        session.add_all(sensor_data_list)
        session.commit()
        logger.info(f"成功插入 {len(sensor_data_list)} 条记录")
        
        # 2. 查询数据（Read）
        logger.info("=== 查询所有数据 ===")
        all_data = session.query(SensorData).all()
        for data in all_data:
            logger.info(data)
        
        logger.info("=== 条件查询 ===")
        # 查询温度高于 25 度的设备
        high_temp_data = session.query(SensorData).filter(
            SensorData.temperature > 25.0
        ).all()
        logger.info(f"温度高于25度的设备数量: {len(high_temp_data)}")
        
        # 查询特定设备的数据
        device_data = session.query(SensorData).filter(
            SensorData.device_id == "device_001"
        ).first()
        logger.info(f"设备001的数据: {device_data}")
        
        # 3. 更新数据（Update）
        logger.info("=== 更新数据 ===")
        if device_data:
            old_temp = device_data.temperature
            device_data.temperature = 27.5
            session.commit()
            logger.info(f"更新设备001温度: {old_temp} -> 27.5")
        
        # 4. 聚合查询
        logger.info("=== 聚合查询 ===")
        # 计算平均温度
        avg_temp = session.query(SensorData.temperature).scalar()
        logger.info(f"平均温度: {avg_temp}")
        
        # 使用原生 SQL 进行复杂查询
        result = session.execute(
            "SELECT COUNT(*), AVG(temperature), AVG(humidity) FROM sensor_data")
        for row in result:
            logger.info(f"统计信息 - 记录数: {row[0]}, 平均温度: {row[1]:.2f}, 平均湿度: {row[2]:.2f}")
        
        # 5. 删除数据（Delete）
        logger.info("=== 删除数据 ===")
        # 删除设备003的数据
        deleted_count = session.query(SensorData).filter(
            SensorData.device_id == "device_003"
        ).delete()
        session.commit()
        logger.info(f"删除 {deleted_count} 条记录")
        
        # 验证删除结果
        remaining_data = session.query(SensorData).count()
        logger.info(f"删除后剩余记录数: {remaining_data}")
        
    except Exception as e:
        logger.error(f"操作失败: {e}")
        session.rollback()
    finally:
        session.close()

def demo_advanced_operations():
    """演示高级操作"""
    engine, SessionLocal = init_database()
    session = SessionLocal()
    
    try:
        # 批量插入性能测试数据
        logger.info("=== 批量插入性能测试 ===")
        batch_data = []
        base_time = datetime.now()
        
        for i in range(10):
            data_time = base_time.replace(second=i)
            batch_data.append(
                SensorData(
                    ts=data_time,
                    device_id=f"batch_device_{i % 3}",
                    temperature=20 + i * 0.5,
                    humidity=60 + i * 0.3,
                    location=f"Batch Location {i}")
            )
        
        session.add_all(batch_data)
        session.commit()
        logger.info(f"批量插入 {len(batch_data)} 条记录")
        
        # 分组查询
        logger.info("=== 分组查询 ===")
        group_result = session.execute(
            text("""
                SELECT device_id, COUNT(*) as count, 
                       AVG(temperature) as avg_temp, 
                       AVG(humidity) as avg_humidity 
                FROM sensor_data 
                GROUP BY device_id
            """)
        )
        
        for row in group_result:
            logger.info(f"设备 {row[0]}: 记录数={row[1]}, 平均温度={row[2]:.2f}, 平均湿度={row[3]:.2f}")
        
        # 时间范围查询
        logger.info("=== 时间范围查询 ===")
        start_time = datetime(2024, 11, 9, 16, 0, 0)
        end_time = datetime(2024, 11, 9, 17, 0, 0)
        
        time_range_data = session.query(SensorData).filter(
            SensorData.ts.between(start_time, end_time)
        ).all()
        
        logger.info(f"时间范围 {start_time} 到 {end_time} 内的记录数: {len(time_range_data)}")
        
    except Exception as e:
        logger.error(f"高级操作失败: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("开始演示 SQLAlchemy + TDengine 操作")
    
    # 基本 CRUD 操作演示
    demo_crud_operations()
    
    # 高级操作演示
    demo_advanced_operations()
    
    logger.info("演示完成")
	
'''
<code_end>
<code_start project_name=python_sqlalchemy_tdengine filename=requirements.txt title=项目依赖文件 entrypoint=false runnable=false project_final_file=true>
sqlalchemy>=1.4.0
taospy>=2.8.5
<code_end>

这个示例演示了如何使用 SQLAlchemy 连接 TDengine 数据库并进行完整的 CRUD 操作。代码的主要功能包括：

**核心功能特点：**
- 使用 TDengine 官方 Python 连接器 taospy 实现 SQLAlchemy 集成
- 支持原生连接和 WebSocket 连接两种方式
- 完整的数据库表模型定义，符合 TDengine 的时间序列数据库特性
- 实现了标准的 CRUD（增删查改）操作模式
- 包含聚合查询、分组统计等高级时间序列分析功能

**技术实现细节：**
1. **数据库连接**：使用 `taosws://` 协议通过 WebSocket 连接 TDengine，这种方式性能较好且依赖较少
2. **表结构设计**：使用 `ts` 字段作为时间戳主键，符合 TDengine 的最佳实践
3. **数据操作**：包含单条插入、批量插入、条件查询、更新和删除操作
4. **高级查询**：演示了时间范围查询、分组聚合等时间序列数据库特有功能

**使用前准备：**
需要安装 taospy 2.8.5 以上版本才能在 SQLAlchemy 中使用 TDengine，可以通过 `pip install taospy[ws]` 安装 WebSocket 连接支持。
'''