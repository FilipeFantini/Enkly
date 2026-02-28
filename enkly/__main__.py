"""Entry point: python -m enkly"""

import argparse

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Enkly — Analytics for the rest of us")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on changes")
    args = parser.parse_args()

    uvicorn.run("enkly.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
