#!/bin/zsh
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python start.py --open
elif [[ -x /Users/xu77/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 ]]; then
  /Users/xu77/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 start.py --open
else
  python3 start.py --open
fi
