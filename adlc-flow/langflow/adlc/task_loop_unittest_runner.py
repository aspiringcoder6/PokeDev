"""Trusted unittest entry point, launched with Python's isolated import mode."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

RESULT_MARKER = "ADLC_UNITTEST_RESULT="


def main() -> None:
    # Import the real runner before exposing the candidate's modules on sys.path.
    path = Path(sys.argv[1])
    sys.path.insert(0, str(Path.cwd()))
    suite = unittest.defaultTestLoader.discover(path.parent.as_posix(), pattern=path.name)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    executed = max(0, result.testsRun - len(result.skipped))
    passed = result.wasSuccessful() and executed > 0
    print(RESULT_MARKER + json.dumps({"executed_tests": executed, "passed": passed}))  # noqa: T201 - subprocess protocol.
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
