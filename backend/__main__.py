"""Run the development API server with ``python -m backend``."""

import uvicorn


def main() -> None:
    """Start the local FastAPI development server."""

    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
