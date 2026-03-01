FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir \
    "fastapi>=0.104.0" \
    "uvicorn[standard]>=0.24.0" \
    "duckdb>=1.0.0" \
    "pyyaml>=6.0" \
    "hatchling"

COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["enkly", "--host", "0.0.0.0", "--port", "8000"]
