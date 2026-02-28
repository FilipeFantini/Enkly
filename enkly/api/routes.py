"""API routes for Enkly."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..engine.connection import DuckDBConnection
from ..engine.query_builder import BuiltQuery, SemanticQuery, build_query
from ..engine.semantic import SemanticModel

router = APIRouter(prefix="/api")

# These get set by the app on startup
_db: DuckDBConnection | None = None
_model: SemanticModel | None = None


def init(db: DuckDBConnection, model: SemanticModel) -> None:
    global _db, _model
    _db = db
    _model = model


# --- Request/Response schemas ---


class QueryRequest(BaseModel):
    metrics: list[str] = []
    dimensions: list[str] = []
    filters: list[dict] = []
    order_by: list[dict] = []
    limit: int | None = 100


class SqlRequest(BaseModel):
    sql: str


class ChartSuggestion(BaseModel):
    type: str  # bar, line, pie, table
    reason: str


class QueryResponse(BaseModel):
    sql: str
    columns: list[dict]
    data: list[dict]
    row_count: int
    chart_suggestion: ChartSuggestion


# --- Endpoints ---


@router.get("/model")
def get_model():
    """Return the current semantic model metadata."""
    if not _model:
        raise HTTPException(status_code=503, detail="No model loaded")

    return {
        "name": _model.name,
        "display_name": _model.display_name,
        "metrics": {
            name: {"display_name": m.display_name, "format": m.format}
            for name, m in _model.metrics.items()
        },
        "dimensions": {
            name: {"display_name": d.display_name}
            for name, d in _model.dimensions.items()
        },
    }


@router.post("/query")
def run_query(req: QueryRequest):
    """Run a semantic query and return results with chart suggestion."""
    if not _db or not _model:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        built: BuiltQuery = build_query(
            _model,
            SemanticQuery(
                metrics=req.metrics,
                dimensions=req.dimensions,
                filters=req.filters,
                order_by=req.order_by,
                limit=req.limit,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        data = _db.execute(built.sql)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query execution error: {e}")

    suggestion = _suggest_chart(built, data, req.dimensions)

    return QueryResponse(
        sql=built.sql,
        columns=built.columns,
        data=data,
        row_count=len(data),
        chart_suggestion=suggestion,
    )


@router.post("/sql")
def run_raw_sql(req: SqlRequest):
    """Execute raw SQL directly (power user mode)."""
    if not _db:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    sql = req.sql.strip()
    if not sql:
        raise HTTPException(status_code=400, detail="Empty SQL")

    # Basic safety: block destructive statements
    first_word = sql.split()[0].upper()
    if first_word in ("DROP", "DELETE", "ALTER", "TRUNCATE", "INSERT", "UPDATE", "CREATE"):
        raise HTTPException(status_code=403, detail=f"{first_word} statements are not allowed")

    try:
        data = _db.execute(sql)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL error: {e}")

    columns = []
    if data:
        columns = [{"name": k, "display_name": k, "type": "raw"} for k in data[0].keys()]

    return {
        "sql": sql,
        "columns": columns,
        "data": data,
        "row_count": len(data),
        "chart_suggestion": {"type": "table", "reason": "Raw SQL query"},
    }


@router.get("/tables")
def list_tables():
    """List all loaded tables and their schemas."""
    if not _db:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    tables = _db.get_tables()
    result = {}
    for t in tables:
        result[t] = _db.get_table_columns(t)
    return result


# --- Chart suggestion logic ---


def _suggest_chart(
    built: BuiltQuery, data: list[dict], dimensions: list[str]
) -> ChartSuggestion:
    """Infer the best chart type from the query shape."""
    if not data:
        return ChartSuggestion(type="table", reason="No data to visualize")

    num_rows = len(data)
    has_dimensions = len(dimensions) > 0
    num_metrics = len([c for c in built.columns if c["type"] == "metric"])

    # Time-based dimension → line chart
    time_keywords = ("month", "week", "day", "date", "year", "quarter")
    has_time_dim = any(d in dim for dim in dimensions for d in time_keywords)

    if has_time_dim and num_metrics >= 1:
        return ChartSuggestion(type="line", reason="Time-series data detected")

    if has_dimensions and num_rows <= 8:
        if num_metrics == 1:
            return ChartSuggestion(type="pie", reason="Few categories with one metric")
        return ChartSuggestion(type="bar", reason="Categorical comparison")

    if has_dimensions and num_rows > 8:
        return ChartSuggestion(type="bar", reason="Multiple categories comparison")

    return ChartSuggestion(type="table", reason="Tabular data")
