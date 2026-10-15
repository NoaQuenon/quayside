import json
import time
from collections.abc import Mapping, Sequence
from csv import DictWriter
from pathlib import Path
from types import TracebackType
from typing import Any, Self


class CsvRecorder:
    def __init__(self, path: Path, fieldnames: Sequence[str], flush_interval: float = 1.0):
        self.path = path
        self.fieldnames = list(fieldnames)

        self._file = path.open("w", newline="")
        self._writer = DictWriter(self._file, fieldnames=self.fieldnames, extrasaction="raise")
        self._writer.writeheader()
        self._flush_interval = flush_interval
        self._last_flush = time.monotonic()

    def write(self, row: Mapping[str, Any]) -> None:
        self._writer.writerow(row)
        now = time.monotonic()

        if now - self._last_flush >= self._flush_interval:
            self._file.flush()
            self._last_flush = now

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> Self:
        return self

    # Apparently thats the right way of typing this function
    # https://stackoverflow.com/a/58808179
    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


class EventLog:
    def __init__(self, path: Path, source: str):
        self.source = source
        self._file = path.open("a", buffering=1)

    def log(self, event: str, **fields: Any) -> None:
        record = {"t": time.time(), "source": self.source, "event": event, **fields}
        self._file.write(json.dumps(record, default=str) + "\n")

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
