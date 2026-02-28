"""FastAPI application — the heart of Enkly."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import routes
from .engine.connection import DuckDBConnection
from .engine.semantic import parse_model

MODELS_DIR = Path("models")
DATA_DIR = Path("data")


def _find_model() -> Path | None:
    """Find the first YAML model in the models directory."""
    if not MODELS_DIR.exists():
        return None
    for ext in ("*.yaml", "*.yml"):
        files = list(MODELS_DIR.glob(ext))
        if files:
            return files[0]
    return None


def _seed_sample_data() -> None:
    """Create sample CSV files if they don't exist."""
    orders_path = DATA_DIR / "orders.csv"
    customers_path = DATA_DIR / "customers.csv"

    if orders_path.exists() and customers_path.exists():
        return

    DATA_DIR.mkdir(exist_ok=True)

    # Sample orders
    import csv
    import random
    from datetime import date, timedelta

    random.seed(42)
    products = ["Notebook", "Caneta", "Caderno", "Mochila", "Calculadora", "Borracha", "Lapis", "Apontador"]
    regions = ["Sul", "Sudeste", "Norte", "Nordeste", "Centro-Oeste"]
    start = date(2024, 1, 1)

    with open(orders_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "customer_id", "product", "quantity", "price", "order_date", "region"])
        for i in range(1, 501):
            d = start + timedelta(days=random.randint(0, 364))
            w.writerow([
                i,
                random.randint(1, 50),
                random.choice(products),
                random.randint(1, 10),
                round(random.uniform(5.0, 200.0), 2),
                d.isoformat(),
                random.choice(regions),
            ])

    # Sample customers
    segments = ["Varejo", "Atacado", "Online"]
    first_names = ["Ana", "Bruno", "Carla", "Diego", "Elena", "Felipe", "Gabriela", "Hugo", "Isabela", "Joao"]
    last_names = ["Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Costa", "Ferreira", "Almeida", "Ribeiro"]

    with open(customers_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "name", "email", "segment"])
        for i in range(1, 51):
            fn = random.choice(first_names)
            ln = random.choice(last_names)
            w.writerow([
                i,
                f"{fn} {ln}",
                f"{fn.lower()}.{ln.lower()}@email.com",
                random.choice(segments),
            ])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Seed sample data
    _seed_sample_data()

    # Find and load model
    model_path = _find_model()
    if not model_path:
        print("Warning: No model found in models/ directory")
        yield
        return

    model = parse_model(str(model_path))
    db = DuckDBConnection()

    # Register all sources
    for source in model.sources.values():
        try:
            db.register_source(source.name, source.path, source.type)
            print(f"  Loaded source: {source.name} ({source.path})")
        except FileNotFoundError as e:
            print(f"  Warning: {e}")

    # Wire up the API
    routes.init(db, model)

    print(f"\n  Enkly ready — model '{model.display_name}' loaded")
    print(f"  Open http://localhost:8000 in your browser\n")

    yield

    db.close()


app = FastAPI(
    title="Enkly",
    description="Analytics for the rest of us",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(routes.router)

# Serve static frontend
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
