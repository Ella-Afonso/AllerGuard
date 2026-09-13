"""Launch a single-process isolated replay surface or local read-only AWS evidence."""

import argparse

import uvicorn

from src.api.app import create_app
from src.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("demo", "aws-evidence"), default="demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--origin", default=None, help="Exact browser origin, required behind HTTPS."
    )
    args = parser.parse_args()
    if args.mode == "aws-evidence" and args.host not in {"127.0.0.1", "localhost"}:
        parser.error("AWS evidence mode must bind to loopback.")
    origin = args.origin or f"http://{args.host}:{args.port}"
    app = create_app(
        origin=origin,
        aws_settings=Settings.from_environment() if args.mode == "aws-evidence" else None,
    )
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
