from sqlalchemy import create_engine, inspect, MetaData, Table, Column, Integer, String

def check_table_exists(engine, table_name):
    """检查表是否存在"""
    inspector = inspect(engine)
    return inspector.has_table(table_name)

def demo_table_existence():
    # 创建 SQLite 内存数据库
    engine = create_engine('sqlite:///:memory:')
    
    # 创建示例表
    metadata = MetaData()
    users = Table('users', metadata,
                 Column('id', Integer, primary_key=True),
                 Column('name', String(50)))
    
    # 创建表
    metadata.create_all(engine)
    
    # 检查表是否存在
    tables_to_check = ['users', 'products', 'orders']
    
    for table_name in tables_to_check:
        exists = check_table_exists(engine, table_name)
        status = "存在" if exists else "不存在"
        print(f"表 {table_name}: {status}")

if __name__ == "__main__":
    demo_table_existence()