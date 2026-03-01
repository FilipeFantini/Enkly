"""API routes for Enkly."""

import json
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..engine.connection import DuckDBConnection
from ..engine.query_builder import BuiltQuery, SemanticQuery, build_query
from ..engine.semantic import SemanticModel

router = APIRouter(prefix="/api")

# These get set by the app on startup
_db: DuckDBConnection | None = None
_model: SemanticModel | None = None
_registry_path: Path | None = None
_uploads_dir: Path | None = None


def init(
    db: DuckDBConnection,
    model: SemanticModel,
    registry_path: Path,
    uploads_dir: Path,
) -> None:
    global _db, _model, _registry_path, _uploads_dir
    _db = db
    _model = model
    _registry_path = registry_path
    _uploads_dir = uploads_dir


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


# --- Catalog ---


@router.get("/catalog")
def get_catalog():
    """Return all tables with stats and schema — the data catalog."""
    if not _db:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    registry = _load_registry()
    registry_by_table = {r["table_name"]: r for r in registry}

    # Source info from semantic model
    model_sources = {}
    if _model:
        for src_name, src in _model.sources.items():
            model_sources[src_name] = {"path": src.path, "type": src.type, "origin": "model"}

    result = []
    for table_name in _db.get_tables():
        try:
            stats = _db.get_table_stats(table_name)
            columns = _db.get_table_columns(table_name)
        except Exception:
            continue

        # Determine source info
        if table_name in model_sources:
            source_info = model_sources[table_name]
        elif table_name in registry_by_table:
            r = registry_by_table[table_name]
            source_info = {"path": r["file_path"], "type": r["file_type"], "origin": "upload"}
        else:
            source_info = {"path": None, "type": "unknown", "origin": "unknown"}

        result.append({
            "table_name": table_name,
            "row_count": stats["row_count"],
            "column_count": stats["column_count"],
            "columns": columns,
            "source": source_info,
        })

    return result


@router.get("/catalog/{table_name}/sample")
def get_table_sample(table_name: str):
    """Return sample rows for a table."""
    if not _db:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    # Validate table name against known tables
    known = _db.get_tables()
    if table_name not in known:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    try:
        rows = _db.get_sample(table_name, limit=20)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    columns = []
    if rows:
        columns = [{"name": k, "display_name": k, "type": "raw"} for k in rows[0].keys()]

    return {"table_name": table_name, "columns": columns, "data": rows}


# --- Upload ---

_ALLOWED_EXTENSIONS = {"csv", "json", "parquet"}


@router.post("/sources/upload")
async def upload_source(file: UploadFile, table_name: str = Form(...)):
    """Upload a file and register it as a table in DuckDB."""
    if not _db or _uploads_dir is None or _registry_path is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    # Validate table name (alphanumeric + underscore only)
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
        raise HTTPException(
            status_code=400,
            detail="Nome da tabela inválido. Use apenas letras, números e _",
        )

    # Detect file type from extension
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo não suportado: .{ext}. Use: {', '.join(_ALLOWED_EXTENSIONS)}",
        )

    # Save file to uploads dir
    _uploads_dir.mkdir(parents=True, exist_ok=True)
    dest = _uploads_dir / f"{table_name}.{ext}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Register in DuckDB
    try:
        _db.register_source(table_name, str(dest), ext)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Erro ao registrar: {e}")

    # Persist to registry
    registry = _load_registry()
    registry = [r for r in registry if r["table_name"] != table_name]  # upsert
    registry.append({
        "table_name": table_name,
        "file_path": str(dest),
        "file_type": ext,
        "original_filename": filename,
    })
    _save_registry(registry)

    # Return sample for preview
    rows = _db.get_sample(table_name, limit=10)
    stats = _db.get_table_stats(table_name)
    columns = _db.get_table_columns(table_name)

    return {
        "table_name": table_name,
        "row_count": stats["row_count"],
        "column_count": stats["column_count"],
        "columns": columns,
        "sample": rows,
    }


def _load_registry() -> list[dict]:
    if _registry_path and _registry_path.exists():
        with open(_registry_path) as f:
            return json.load(f)
    return []


def _save_registry(registry: list[dict]) -> None:
    if _registry_path:
        with open(_registry_path, "w") as f:
            json.dump(registry, f, indent=2)


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
