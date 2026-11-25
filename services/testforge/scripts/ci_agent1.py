"""Portable CI entrypoint; no dependency on GitHub/GitLab/Jenkins syntax."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile")
    parser.add_argument("--suite")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = root / "artifacts/ci"
    report.mkdir(parents=True, exist_ok=True)
    unit = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", f"--junitxml={report / 'unit.xml'}"], cwd=root)
    if unit.returncode:
        return unit.returncode
    if bool(args.profile) != bool(args.suite):
        parser.error("--profile and --suite must be provided together")
    if args.profile:
        return subprocess.run([sys.executable, "scripts/run_staging.py", "--profile", args.profile, "--suite", args.suite], cwd=root).returncode
    print("Unit checks passed. No staging suite requested; no staging gate has been evaluated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
