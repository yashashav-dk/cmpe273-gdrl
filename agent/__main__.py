import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from main import main  # noqa: E402

parser = argparse.ArgumentParser(description="gdrl AI traffic shaping agent")
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Run the full agent loop (predict + decide + log) without writing policies to Redis. "
         "Use this for demo rehearsals to avoid polluting live policy state.",
)
args = parser.parse_args()

main(dry_run=args.dry_run)
