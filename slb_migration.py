#!python
# encoding: utf-8

import click
import click_shell
from rich import print as pprint
from rich import console
from rich.console import Console

from difoss_stock_util import *
from difoss_stock_util.db_util import generate_engine_url_str
from difoss_stock_util.color_log_util import *

from sqlalchemy.orm import declared_attr, declarative_base
from sqlalchemy import (
    Column, Integer, String, DateTime, Index, func, JSON,
    create_engine, text, select, Engine
)
from datetime import datetime

from difoss_stock_util.metric_data import SLBDetail

# --------------------------------------------------------------------------------
# Global Variables
CONSOLE = console.Console()

# --------------------------------------------------------------------------------
# 全局变量
CONSOLE = Console()
CFG = None
# Define globally after config load
PG_URL = None # type: str | None
SQLITE_URL = None # type: str | None
PG_ENGINE = None # type: Engine | None
SQLITE_ENGINE = None # type: Engine | None

# --------------------------------------------------------------------------------
# Utils
def initialize_engines_and_models():
    """Initialize engines and models after CFG and URLs are loaded."""
    global PG_ENGINE, SQLITE_ENGINE, PG_URL, SQLITE_URL, CFG
    CFG = read_yaml_config() # type: dict
    if not CFG:
        raise RuntimeError("Configuration must be loaded before initializing engines/models.")

    pg_cfg = CFG.get('postgresql', {})
    sqlite_cfg = CFG.get('sqlite', {'database' : ':memory:'})

    PG_URL = generate_engine_url_str(**pg_cfg)
    SQLITE_URL = generate_engine_url_str(**sqlite_cfg)

    # Create engines directly
    PG_ENGINE = create_engine(PG_URL)
    SQLITE_ENGINE = create_engine(SQLITE_URL)



def sync_data_with_raw_sql(source_engine: Engine, target_model: SLBDetail, limit=None):
    """
    Alternative: Sync data using raw SQL strings.
    Useful if Core expressions become too complex or for maximum control.
    """
    table_name = target_model.__tablename__
    I(table_name=target_model)

    columns = [f'"{x}"' for x in target_model.__table__.columns.keys()] # 添加 "" 包裹 column_name 防止大小写自动转换
    columns_str = ", ".join(columns)

    # 1. Build the SELECT query string
    select_sql = f"SELECT {columns_str} FROM {table_name}"
    if limit and limit > 0:
        select_sql += f" LIMIT {limit}"

    # 2. Execute SELECT on source
    CONSOLE.print(f"[green]Fetching data from source (raw SQL)...[/green]")
    with source_engine.connect() as conn:
        result = conn.execute(text(select_sql))
        rows = result.fetchall()
        column_names = result.keys()

    column_names: list[str]
    column_names = [col for col in column_names if col != 'id'] # 去掉 id 以达到重排的目的（因为之前的库id可能已经乱序）

    CONSOLE.print(f"[green]Fetched {len(rows)} records from source (raw SQL).[/green]")

    if not rows:
        CONSOLE.print("[yellow]No data to sync (raw SQL).[/yellow]")
        return

    CONSOLE.print(f"type(rows)={type(rows)}, type(row[0])={type(rows[0])} ")
    CONSOLE.print(f"row[0]={rows[0]} ")
    data_dicts = [dict(zip(column_names, row)) for row in rows]
    CONSOLE.print(f"type(data_dicts[0])={type(data_dicts[0])} ")

    CONSOLE.print(f"[green]Inserting data into target (raw SQL fetch, Core insert)...[/green]")
    target_model.batch_insert(data_dicts)

    sqlite_rows = target_model.get_all(limit)
    rows_dict = [x.to_dict() for x in sqlite_rows]
    CONSOLE.print(f"rows[limit={limit}] in SQLite: {rows_dict}")

    CONSOLE.print(f"[green]Successfully synced {len(rows)} records to target (raw SQL/Core hybrid).[/green]")
