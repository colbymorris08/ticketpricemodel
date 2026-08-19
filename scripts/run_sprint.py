#!/usr/bin/env python3
"""Run full sprint: fixtures → snapshot → features → recommendations."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run_step(name: str, cmd: list[str]) -> None:
    print(f"\n{'='*60}\nSTEP: {name}\n{'='*60}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ticket price model sprint")
    parser.add_argument("--as-of", default="2026-08-18")
    parser.add_argument("--no-live", action="store_true", help="Skip live StubHub fetch")
    args = parser.parse_args()

    py = sys.executable
    run_step("1 · Load fixtures", [py, str(SCRIPTS / "fetch_schedule.py"), "--as-of", args.as_of])
    snap_cmd = [py, str(SCRIPTS / "snapshot_secondary.py"), "--as-of", args.as_of]
    if args.no_live:
        snap_cmd.append("--no-live")
    run_step("2 · Snapshot secondary prices", snap_cmd)
    run_step("3 · Build features", [py, str(SCRIPTS / "build_features.py"), "--as-of", args.as_of])
    run_step("4 · Train + recommendations", [py, str(SCRIPTS / "train_predict.py"), "--as-of", args.as_of])
    print("\nSprint complete. See results/recommendations.csv")


if __name__ == "__main__":
    main()
