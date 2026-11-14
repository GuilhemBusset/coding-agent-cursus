"""Install Session 2 from its local locks, then check offline readiness (all student OSes).

uv run --no-project --python 3.12 python setup/session-02-research-agents.py
Requires mise and uv from the existing student installer. No logins or API key required.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from student.prepare import RETRY_DELAYS_S, run_quiet, sync


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path,
                        default=Path(__file__).resolve().parents[1] / "sessions/02-research-agents")
    args = parser.parse_args()
    session = args.session.resolve()
    if sync(session.parent, session, RETRY_DELAYS_S):
        return 1
    code, output = run_quiet(["mise", "exec", "--", "uv", "run", "--locked", "python",
                              "exercises/check_setup.py"], session)
    print(output, end="")
    return code


if __name__ == "__main__":
    sys.exit(main())
