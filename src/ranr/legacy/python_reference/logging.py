"""Append-only compressed raw records, outside source and bounded in memory."""

from __future__ import annotations
import gzip
import json
import io
from pathlib import Path


class RecordLog:
    def __init__(self, path: Path):
        self.raw = path.open("wb")
        self.handle = io.TextIOWrapper(
            gzip.GzipFile(
                filename="", fileobj=self.raw, mode="wb", mtime=0, compresslevel=6
            ),
            encoding="utf-8",
            newline="\n",
        )
        self.rows = 0

    def append(self, row: dict) -> None:
        self.handle.write(
            json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n"
        )
        self.rows += 1

    def close(self) -> None:
        self.handle.close()
        self.raw.close()
