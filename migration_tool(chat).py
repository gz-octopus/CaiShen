
import sqlite3
import psycopg2
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL as EngineUrl
from typing import Optional
from difoss_stock_util import *
from difoss_stock_util.color_log_util import *



import sqlite3
import psycopg2
from psycopg2.extras import execute_values

def migrate_sqlite_to_postgresql(sqlite_db_path, postgresql_url: EngineUrl):
    # 连接数据库
    sqlite_conn = sqlite3.connect(sqlite_db_path)
    pg_conn = psycopg2.connect(
        host=postgresql_url.host,
        database=postgresql_url.database,
        user=postgresql_url.username,
        password=postgresql_url.password,
        port=postgresql_url.port,
    )

    # 获取 SQLite 表结构
    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = sqlite_cursor.fetchall()

    # 类型映射字典
    type_mapping = {
        'INTEGER': 'BIGINT',
        'REAL': 'DOUBLE PRECISION',
        'TEXT': 'TEXT',
        'BLOB': 'BYTEA',
        'NUMERIC': 'NUMERIC',
        'BOOLEAN': 'BOOLEAN',
        'DATETIME': 'TIMESTAMP',
        'DATE': 'DATE'
    }

    pg_cursor = pg_conn.cursor()

    for table in tables:
        table_name = table[0]
        
        # 获取表结构
        sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
        columns = sqlite_cursor.fetchall()
        
        '''不能通过自己拼装来创建 PG 表，需要用 sqlalchemy 的 BaseModel 继承类来创建，字段很多不兼容'''
        # 创建 PostgreSQL 表
        # create_table_sql = f"CREATE TABLE {table_name} ("
        # for col in columns:
        #     col_name = col[1]
        #     col_type = col[2].upper()
        #     pg_type = type_mapping.get(col_type, 'TEXT')
        #     create_table_sql += f"{col_name} {pg_type},"
        # create_table_sql = create_table_sql.rstrip(',') + ");"
        
        # pg_cursor.execute(create_table_sql)
        
        # 迁移数据
        sqlite_cursor.execute(f"SELECT * FROM {table_name}")
        rows = sqlite_cursor.fetchall()
        
        if rows:
            col_names = [col[1] for col in columns]
            insert_sql = f"INSERT INTO {table_name} ({','.join(col_names)}) VALUES %s"
            execute_values(pg_cursor, insert_sql, rows)

    pg_conn.commit()
    sqlite_conn.close()
    pg_conn.close()


def migrate_sqlite_to_postgresql_baidu(sqlite_db_path, pg_url: EngineUrl):
    """
    将SQLite数据库迁移到PostgreSQL
    """
    # 连接SQLite数据库
    sqlite_conn = sqlite3.connect(sqlite_db_path)

    # 获取所有表名
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    # 连接PostgreSQL
    postgres_engine = create_engine(pg_url.render_as_string(False))

    # 迁移每张表
    for table in tables:
        print(f"正在迁移表: {table}")

        # 从SQLite读取数据
        df = pd.read_sql_query(f"SELECT * FROM {table}", sqlite_conn)

        # 写入PostgreSQL
        df.to_sql(
            name=table,
            con=postgres_engine,
            if_exists='replace',
            index=False,
            chunksize=1000
        )

    # 关闭连接
    sqlite_conn.close()
    postgres_engine.dispose()
    print("数据迁移完成！")
    
    
def main():
    CFG = read_yaml_config()
    if CFG is None:
        raise Exception("无法读取配置文件 config.yaml")
    
    # SQLite数据库文件路径
    I(cfg=CFG)
    
    sqlite_db = CFG['sqlite']['db-file']
    pg_login_info = CFG['postgresql']
    # PostgreSQL连接字符串
    pg_url = EngineUrl.create(**pg_login_info)
    
    postgres_conn = CFG['postgresql']['db-url']
    migrate_sqlite_to_postgresql(sqlite_db, pg_url)

if __name__ == "__main__":
    main()
