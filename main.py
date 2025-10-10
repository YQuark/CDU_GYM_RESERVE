from __future__ import annotations

import sys

from cli import main as cli_main
from ql import run_in_ql_mode


def _dispatch(argv: list[str]) -> int:
    if len(argv) <= 1:
        return run_in_ql_mode()
    return cli_main(argv[1:])


if __name__ == "__main__":
    sys.exit(_dispatch(sys.argv))
