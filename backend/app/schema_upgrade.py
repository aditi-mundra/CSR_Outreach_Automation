"""Add newly introduced nullable columns to existing tables at startup.

`Base.metadata.create_all` creates missing *tables* but never alters
existing ones, so a database created before a column was added (e.g.
`contacts.priority` from contact discovery) would make every query on
that table fail. This app deliberately has no migration tool (see
docs/DEPLOYMENT.md), so this module covers the one safe, common case:
a new *nullable* column is added with `ALTER TABLE ... ADD COLUMN`.

Anything else (renames, type changes, NOT NULL columns) is skipped with a
warning and still needs a manual change - same as before.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .database import Base

logger = logging.getLogger("schema_upgrade")


def _column_ddl(column, dialect) -> str:
    ddl = f'"{column.name}" {column.type.compile(dialect=dialect)}'
    foreign_keys = list(column.foreign_keys)
    if foreign_keys:
        fk = foreign_keys[0]
        target = fk.column
        ddl += f' REFERENCES "{target.table.name}" ("{target.name}")'
        if fk.ondelete:
            ddl += f" ON DELETE {fk.ondelete}"
    return ddl


def add_missing_columns(engine: Engine) -> list[str]:
    """Add every nullable model column missing from an existing table.

    Returns "table.column" for each column added. Idempotent: a second
    run finds nothing to do.
    """
    inspector = inspect(engine)
    added: list[str] = []
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # create_all makes it with every column
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable or column.primary_key:
                    logger.warning(
                        "Column %s.%s is missing but NOT NULL - add it by hand.", table.name, column.name
                    )
                    continue
                connection.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN {_column_ddl(column, engine.dialect)}')
                )
                added.append(f"{table.name}.{column.name}")
    for name in added:
        logger.info("Added missing column %s", name)
    return added
