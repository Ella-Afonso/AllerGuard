"""Archive a reviewed public/synthetic file to an explicitly selected S3 bucket."""

import argparse
from pathlib import Path

from src.tools.storage import store_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument("--public-or-synthetic", action="store_true", required=True)
    args = parser.parse_args()
    receipt = store_file(args.path, bucket=args.bucket, prefix=args.prefix, region=args.region)
    print(receipt.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
