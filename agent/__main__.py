import os
import sys

# Direct imports in main.py (from decider import ...) resolve relative to agent/.
# When invoked as `python -m agent` from the repo root, agent/ isn't on sys.path,
# so we add it explicitly before importing main.
sys.path.insert(0, os.path.dirname(__file__))

from main import main  # noqa: E402

main()
