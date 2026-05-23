"""Example: push pytest-benchmark results to sidegit.

Usage:
    pytest --benchmark-json=bench.json
    python examples/attach-pytest-benchmark.py bench.json --url http://localhost:5000

Posts one record per commit (current HEAD), with one entry per benchmark in `data`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import requests


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("benchmark_json", help="Path to pytest-benchmark --benchmark-json output")
    p.add_argument("--url", default="http://127.0.0.1:5000", help="sidegit base URL")
    p.add_argument("--tag", action="append", default=[], metavar="K=V",
                   help="Tag key=value (repeatable)")
    args = p.parse_args()

    commit_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    bench = json.loads(open(args.benchmark_json).read())

    data = {
        b["name"]: {
            "mean": b["stats"]["mean"],
            "stddev": b["stats"]["stddev"],
            "rounds": b["stats"]["rounds"],
        }
        for b in bench.get("benchmarks", [])
    }
    tags = dict(t.split("=", 1) for t in args.tag)

    res = requests.post(
        f"{args.url}/api/records",
        json={"commit_hash": commit_hash, "data": data, "tags": tags or None},
        timeout=30,
    )
    res.raise_for_status()
    record = res.json()
    print(f"Recorded {len(data)} benchmarks under record {record['id']}")

    # Attach the raw benchmark JSON as a blob for later inspection.
    with open(args.benchmark_json, "rb") as f:
        files = {"file": (args.benchmark_json, f, "application/json")}
        res = requests.post(
            f"{args.url}/api/records/{record['id']}/blobs",
            files=files,
            data={"name": "benchmark.json"},
            timeout=120,
        )
    res.raise_for_status()
    print(f"Attached {args.benchmark_json} as blob {res.json()['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
