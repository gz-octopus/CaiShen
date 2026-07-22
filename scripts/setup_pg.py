"""PG 存储基础设施初始化 — 为 quant_lab 研究内核准备数据库。

前置条件:
    - PG_* 五个环境变量已设（PG_HOST/PG_PORT/PG_USERNAME/PG_PASSWORD/PG_DATABASE）
    - PostgreSQL 服务已运行
    - config.yaml postgresql 段已配置 host/port/username/password/database

工作内容:
    1. 幂等创建目标数据库
    2. 初始化 history_data_1d 分区表（父表 + 年度分区）
    3. 添加 adj_factor 复权因子列（默认 NULL，待 P3 补数据源）
"""

import os
import sys

# ── 确保能 import difoss_stock_util（同仓库依赖）──
_CWD = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_CWD)
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

import sqlalchemy as sa
from sqlalchemy import text

# ═══════════════════════════════════════════════════════════════
# 连接组装（从环境变量，不依赖 config.yaml 的 ${} 展开）
# ═══════════════════════════════════════════════════════════════

def _get_env_or_die(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"[FATAL] 环境变量 {name} 未设置")
        sys.exit(1)
    return val


def _assemble_url(database: str) -> str:
    """组装 PostgreSQL 连接 URL（SQLAlchemy 格式）"""
    host = _get_env_or_die("PG_HOST")
    port = os.getenv("PG_PORT", "5432")
    username = _get_env_or_die("PG_USERNAME")
    password = _get_env_or_die("PG_PASSWORD")
    return f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"


# ═══════════════════════════════════════════════════════════════
# 步骤 1：创建目标数据库（幂等）
# ═══════════════════════════════════════════════════════════════

def create_database(admin_url: str, db_name: str):
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :db"),
            {"db": db_name},
        ).fetchone()
        if row:
            print(f"  [SKIP] 数据库 {db_name} 已存在")
        else:
            conn.execute(text(f'CREATE DATABASE "{db_name}" ENCODING \'UTF8\''))
            print(f"  [OK] 数据库 {db_name} 创建成功")
    engine.dispose()


# ═══════════════════════════════════════════════════════════════
# 步骤 2：初始化表结构
# ═══════════════════════════════════════════════════════════════

def init_tables(target_url: str):
    from difoss_stock_util.metric_data.history_data_1d import HistoryData1D
    HistoryData1D.init_db(target_url)
    print("  [OK] history_data_1d 父表初始化完成")


# ═══════════════════════════════════════════════════════════════
# 步骤 3：创建年度分区（幂等）
# ═══════════════════════════════════════════════════════════════

def create_yearly_partitions(target_url: str, start_year: int, end_year: int):
    engine = sa.create_engine(target_url)
    created = []
    with engine.connect() as conn:
        for year in range(start_year, end_year + 1):
            sql = (
                f"CREATE TABLE IF NOT EXISTS history_data_1d_y{year} "
                f"PARTITION OF history_data_1d "
                f"FOR VALUES FROM ({year}0101) TO ({year + 1}0101)"
            )
            try:
                conn.execute(text(sql))
                conn.commit()
                created.append(str(year))
            except Exception:
                conn.rollback()
    engine.dispose()
    if created:
        print(f"  [OK] 年度分区: {created[0]}~{created[-1]}")
    else:
        print("  [SKIP] 分区已存在")


# ═══════════════════════════════════════════════════════════════
# 步骤 4：添加 adj_factor 列（幂等）
# ═══════════════════════════════════════════════════════════════

def add_adj_factor_column(target_url: str):
    engine = sa.create_engine(target_url)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'history_data_1d' AND column_name = 'adj_factor'"
        )).fetchone()
        if row:
            print("  [SKIP] adj_factor 列已存在")
        else:
            conn.execute(text(
                "ALTER TABLE history_data_1d ADD COLUMN adj_factor NUMERIC(12, 6) DEFAULT NULL"
            ))
            conn.commit()
            print("  [OK] adj_factor 列添加成功（默认 NULL，待 P3 补数据源）")
    engine.dispose()


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def main():
    db_name = _get_env_or_die("PG_DATABASE")
    admin_url = _assemble_url("postgres")
    target_url = _assemble_url(db_name)

    print(f"=== quant_lab PG 存储初始化 ===")
    print(f"  目标库: {db_name}")
    print()

    print("[1/4] 创建数据库...")
    create_database(admin_url, db_name)

    print("[2/4] 初始化表结构...")
    init_tables(target_url)

    print("[3/4] 创建年度分区 (2020~2030)...")
    create_yearly_partitions(target_url, 2020, 2030)

    print("[4/4] 添加 adj_factor 复权因子列...")
    add_adj_factor_column(target_url)

    print()
    print("✓ 初始化完成。下一步:")
    print("  cd D:\\quant\\CaiShen")
    print("  python _repl.py sync-history -s 20200101")


if __name__ == "__main__":
    main()
