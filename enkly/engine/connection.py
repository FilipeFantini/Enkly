"""DuckDB connection manager."""

from pathlib import Path

import duckdb


class DuckDBConnection:
    """Manages a DuckDB connection with source registration."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)

    def register_csv(self, table_name: str, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {file_path}")
        self.conn.execute(
            f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_csv_auto('{path}')"
        )

    def register_parquet(self, table_name: str, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Parquet not found: {file_path}")
        self.conn.execute(
            f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_parquet('{path}')"
        )

    def register_json(self, table_name: str, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"JSON not found: {file_path}")
        self.conn.execute(
            f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_json_auto('{path}')"
        )

    def register_source(self, table_name: str, file_path: str, file_type: str) -> None:
        loaders = {
            "csv": self.register_csv,
            "parquet": self.register_parquet,
            "json": self.register_json,
        }
        loader = loaders.get(file_type)
        if not loader:
            raise ValueError(f"Unsupported source type: {file_type}. Use: {list(loaders.keys())}")
        loader(table_name, file_path)

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        """Execute SQL and return results as list of dicts."""
        if params:
            result = self.conn.execute(sql, params)
        else:
            result = self.conn.execute(sql)

        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def execute_raw(self, sql: str) -> tuple[list[str], list[tuple]]:
        """Execute SQL and return (columns, rows) tuple."""
        result = self.conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return columns, rows

    def get_tables(self) -> list[str]:
        result = self.conn.execute("SHOW TABLES")
        return [row[0] for row in result.fetchall()]

    def get_table_columns(self, table_name: str) -> list[dict]:
        result = self.conn.execute(f"DESCRIBE {table_name}")
        return [
            {"name": row[0], "type": row[1], "nullable": row[2] == "YES"}
            for row in result.fetchall()
        ]

    def get_table_stats(self, table_name: str) -> dict:
        count = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        columns = self.get_table_columns(table_name)
        return {"row_count": count, "column_count": len(columns)}

    def get_sample(self, table_name: str, limit: int = 20) -> list[dict]:
        return self.execute(f"SELECT * FROM {table_name} LIMIT {limit}")

    def close(self) -> None:
        self.conn.close()
