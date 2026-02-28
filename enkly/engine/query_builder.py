"""Query builder — translates semantic queries into SQL."""

from dataclasses import dataclass, field

from .semantic import SemanticModel


@dataclass
class SemanticQuery:
    metrics: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    order_by: list[dict] = field(default_factory=list)
    limit: int | None = None


@dataclass
class BuiltQuery:
    sql: str
    columns: list[dict]  # [{name, display_name, type}]


def build_query(model: SemanticModel, query: SemanticQuery) -> BuiltQuery:
    """Build SQL from a semantic query against a model."""
    select_parts = []
    group_by_parts = []
    columns_meta = []
    tables_needed: set[str] = set()
    joins_needed: set[str] = set()

    # Add dimensions to SELECT and GROUP BY
    for dim_name in query.dimensions:
        dim = model.dimensions.get(dim_name)
        if not dim:
            raise ValueError(f"Unknown dimension: {dim_name}")

        alias = dim.display_name
        select_parts.append(f"  {dim.expression} AS \"{alias}\"")
        group_by_parts.append(dim.expression)
        columns_meta.append({"name": dim_name, "display_name": alias, "type": "dimension"})

        # Track which tables are referenced
        _track_tables(dim.expression, model, tables_needed)
        for join in dim.requires_join:
            joins_needed.add(join)

    # Add metrics to SELECT
    for met_name in query.metrics:
        met = model.metrics.get(met_name)
        if not met:
            raise ValueError(f"Unknown metric: {met_name}")

        alias = met.display_name
        select_parts.append(f"  {met.expression} AS \"{alias}\"")
        columns_meta.append({
            "name": met_name,
            "display_name": alias,
            "type": "metric",
            "format": met.format,
        })
        _track_tables(met.expression, model, tables_needed)

    # Determine the primary (FROM) table — first entity referenced
    if not tables_needed:
        # Fallback: use first entity
        primary_table = next(iter(model.entities))
    else:
        primary_table = next(iter(tables_needed))

    # Build FROM + JOINs
    from_clause = f"FROM {primary_table}"
    join_clauses = []

    other_tables = (tables_needed | joins_needed) - {primary_table}
    for table in other_tables:
        join_info = _find_join(model, primary_table, table)
        if join_info:
            join_clauses.append(
                f"LEFT JOIN {table} ON {join_info['on']}"
            )

    # Build WHERE
    where_parts = []
    for f in query.filters:
        dim = model.dimensions.get(f.get("dimension", ""))
        if dim:
            expr = dim.expression
        else:
            expr = f.get("dimension", f.get("expression", ""))

        op = f.get("operator", "=")
        value = f.get("value")

        if isinstance(value, str):
            where_parts.append(f"{expr} {op} '{value}'")
        elif value is not None:
            where_parts.append(f"{expr} {op} {value}")

    # Build ORDER BY
    order_parts = []
    for ob in query.order_by:
        field_name = ob.get("field", "")
        direction = ob.get("direction", "asc").upper()

        # Check if it's a metric or dimension
        met = model.metrics.get(field_name)
        dim = model.dimensions.get(field_name)
        if met:
            order_parts.append(f"\"{met.display_name}\" {direction}")
        elif dim:
            order_parts.append(f"\"{dim.display_name}\" {direction}")
        else:
            order_parts.append(f"{field_name} {direction}")

    # Assemble SQL
    sql_parts = [
        "SELECT",
        ",\n".join(select_parts),
        from_clause,
    ]

    for jc in join_clauses:
        sql_parts.append(jc)

    if where_parts:
        sql_parts.append("WHERE " + " AND ".join(where_parts))

    if group_by_parts:
        sql_parts.append("GROUP BY " + ", ".join(group_by_parts))

    if order_parts:
        sql_parts.append("ORDER BY " + ", ".join(order_parts))

    if query.limit:
        sql_parts.append(f"LIMIT {query.limit}")

    sql = "\n".join(sql_parts)
    return BuiltQuery(sql=sql, columns=columns_meta)


def _track_tables(expression: str, model: SemanticModel, tables: set[str]) -> None:
    """Find which entity tables are referenced in an expression."""
    for entity_name in model.entities:
        if f"{entity_name}." in expression:
            tables.add(entity_name)


def _find_join(
    model: SemanticModel, from_table: str, to_table: str
) -> dict | None:
    """Find join condition between two tables using relationships."""
    for rel in model.relationships:
        from_parts = rel.from_field.split(".")
        to_parts = rel.to_field.split(".")

        if from_parts[0] == from_table and to_parts[0] == to_table:
            return {"on": f"{rel.from_field} = {rel.to_field}"}
        if from_parts[0] == to_table and to_parts[0] == from_table:
            return {"on": f"{rel.to_field} = {rel.from_field}"}

    return None
