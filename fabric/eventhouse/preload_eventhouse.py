#!/usr/bin/env python3
"""Preload the Eventhouse with the generated recent history (``artifacts/data/eventhouse``).

Idempotent: each table is cleared, then re-ingested with the streaming REST API in
chunks under the 4 MB streaming limit. Row counts are checked against the CSVs.

  python -m fabric.eventhouse.preload_eventhouse [--tables dem_telemetry agent_traces]
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import time
from typing import Iterator, List

from fabric._shared.helpers import (deploy_context, get_kusto_token, kusto_mgmt,
                                    kusto_query, kusto_streaming_ingest, print_step,
                                    require_state)
from fabric._shared.paths import EVENTHOUSE_DATA
from fabric.data.schema import EVENTHOUSE

MAX_CHUNK_BYTES = 3 * 1024 * 1024


def chunks(lines: List[str], max_bytes: int = MAX_CHUNK_BYTES) -> Iterator[str]:
    """Split CSV data lines (no header) into payloads under ``max_bytes``."""
    buf: List[str] = []
    size = 0
    for line in lines:
        n = len(line.encode("utf-8")) + 1
        if buf and size + n > max_bytes:
            yield "\n".join(buf) + "\n"
            buf, size = [], 0
        buf.append(line)
        size += n
    if buf:
        yield "\n".join(buf) + "\n"


def count(quri: str, ktok: str, db: str, table: str) -> int:
    return int(kusto_query(quri, ktok, db, f"{table} | count")[0][0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tables", nargs="*", default=list(EVENTHOUSE))
    args = ap.parse_args()

    cfg, state, api, ws, token = deploy_context()
    quri = require_state(state, "kusto_query_uri")
    db = cfg["eventhouse"]["kql_database"]
    ktok = get_kusto_token(quri)

    for i, table in enumerate(args.tables, 1):
        print_step(i, len(args.tables), table)
        path = EVENTHOUSE_DATA / f"{table}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing: run `python -m fabric.data.generate_data`")
        lines = path.read_text(encoding="utf-8").splitlines()
        header, rows = lines[0], [l for l in lines[1:] if l]
        expected = [c for c, _ in EVENTHOUSE[table]]
        if header.split(",") != expected:
            raise ValueError(f"{table}: CSV header differs from schema.EVENTHOUSE")
        kusto_mgmt(quri, ktok, db, f".clear table {table} data")
        parts = list(chunks(rows))
        for payload in parts:
            kusto_streaming_ingest(quri, ktok, db, table, payload)
        n = 0
        for _ in range(12):
            n = count(quri, ktok, db, table)
            if n >= len(rows):
                break
            time.sleep(5)
        status = "OK" if n == len(rows) else "MISMATCH"
        print(f"   {len(rows):,} rows in {len(parts)} chunk(s), table has {n:,}  [{status}]")
        if n != len(rows):
            raise RuntimeError(f"{table}: expected {len(rows)} rows, found {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
