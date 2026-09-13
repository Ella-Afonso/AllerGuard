"""Explicit CLI for packaging or provisioning a synthetic cycle proof."""

import argparse
from pathlib import Path

from src.tools.cycle_proof import package_cycle, provision_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    package = actions.add_parser("package")
    package.add_argument("--folder", type=Path, required=True)
    package.add_argument("--archive", type=Path, required=True)
    provision = actions.add_parser("provision")
    provision.add_argument("--prefix", required=True)
    args = parser.parse_args()
    if args.action == "package":
        package_cycle(args.folder, args.archive)
        print("Lambda archive prepared:", args.archive)
    else:
        settings = provision_cycle(args.prefix)
        print("Synthetic proof tables ready:", settings.dynamodb_table_audit)


if __name__ == "__main__":
    main()
