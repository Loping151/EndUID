"""热重载安全的自动补列。

trans_adapter 里的 exec_list 只在 @on_core_start_before 执行；插件热重载 (reload_plugin)
不会重跑 start-before 钩子，于是「模型已加新列、实表还没有」时全表 ORM 查询会报 no such
column。这里配合 @on_core_start（reload 会重跑本插件该钩子）兜底：逐表对比模型列与实表列，
把模型有、实表缺的列 ALTER ADD 补上。幂等；表不存在则跳过（create_all 负责建表）。每条 ALTER
独立事务，互不影响。

表清单不手写：从调用方模块名推出本插件包前缀，扫 SQLModel 子类收集该前缀下的 table 即可，
新增表/列自动覆盖。
"""
from typing import List, Optional

from sqlmodel import SQLModel
from sqlalchemy import text
from sqlalchemy import inspect as sa_inspect

from gsuid_core.logger import logger
from gsuid_core.utils.database.base_models import engine


def _plugin_prefix(module_name: str) -> str:
    marker = ".utils.database.models"
    if module_name.endswith(marker):
        return module_name[: -len(marker)]
    return module_name.rsplit(".", 1)[0]


def _plugin_tables(module_name: str) -> List:
    prefix = _plugin_prefix(module_name) + "."
    names = set()
    stack = list(SQLModel.__subclasses__())
    seen_cls = set()
    while stack:
        cls = stack.pop()
        if id(cls) in seen_cls:
            continue
        seen_cls.add(id(cls))
        stack.extend(cls.__subclasses__())
        table = getattr(cls, "__table__", None)
        if table is None:
            continue
        if (cls.__module__ or "").startswith(prefix):
            names.add(table.name)
    return [
        SQLModel.metadata.tables[name]
        for name in names
        if name in SQLModel.metadata.tables
    ]


def _default_clause(column) -> Optional[str]:
    server_default = column.server_default
    if server_default is not None:
        arg = getattr(server_default, "arg", None)
        text_val = getattr(arg, "text", None)
        if text_val is not None:
            return text_val
        if arg is not None:
            return str(arg)
    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        value = default.arg
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
    return None


def _add_column_sql(table_name: str, column, dialect) -> str:
    type_sql = column.type.compile(dialect=dialect)
    sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {type_sql}'
    default_clause = _default_clause(column)
    if default_clause is not None:
        sql += f" DEFAULT {default_clause}"
        if not column.nullable:
            sql += " NOT NULL"
    return sql


async def auto_add_missing_columns(
    module_name: str,
    log_prefix: str = "[自动补列]",
) -> None:
    tables = _plugin_tables(module_name)
    if not tables:
        return

    def _existing_columns(sync_conn, table_name):
        insp = sa_inspect(sync_conn)
        if not insp.has_table(table_name):
            return None
        return {col["name"] for col in insp.get_columns(table_name)}

    pending: List[str] = []
    try:
        async with engine.connect() as conn:
            dialect = conn.dialect
            for table in tables:
                existing = await conn.run_sync(_existing_columns, table.name)
                if existing is None:
                    continue
                for column in table.columns:
                    if column.name not in existing:
                        pending.append(_add_column_sql(table.name, column, dialect))
    except Exception as e:
        logger.warning(f"{log_prefix} 读取表结构失败: {e}")
        return

    for sql in pending:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
            logger.info(f"{log_prefix} {sql}")
        except Exception as e:
            logger.warning(f"{log_prefix} 执行失败: {sql} -> {e}")
