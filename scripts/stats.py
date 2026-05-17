import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class StatsTracker:
    def __init__(self, stats_path: Path, book_name: str) -> None:
        self._path = stats_path
        self._book_name = book_name
        self._lock = threading.Lock()
        self._last_write_time = 0.0
        self._write_interval = 30.0
        self._run_index: int | None = None

    def start_run(self) -> None:
        data = self._load()
        runs = data.setdefault(self._book_name, [])
        entry = {
            "date": datetime.now(timezone.utc).isoformat(),
            "completed": False,
            "duration_seconds": 0,
            "translation": {"total": 0, "input": 0, "input_cache": 0, "output": 0},
            "fill": {"total": 0, "input": 0, "input_cache": 0, "output": 0},
        }
        runs.append(entry)
        self._run_index = len(runs) - 1
        self._save(data)

    def update(self, translation_llm, fill_llm, elapsed: float, force: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and (now - self._last_write_time) < self._write_interval:
                return
            self._last_write_time = now

        data = self._load()
        self._fill_entry(data, translation_llm, fill_llm, elapsed, completed=False)
        self._save(data)

    def complete(self, translation_llm, fill_llm, elapsed: float) -> None:
        with self._lock:
            self._last_write_time = time.monotonic()
        data = self._load()
        self._fill_entry(data, translation_llm, fill_llm, elapsed, completed=True)
        self._save(data)

    def accumulated(self) -> dict:
        data = self._load()
        runs = data.get(self._book_name, [])
        totals = {"total": 0, "input": 0, "input_cache": 0, "output": 0}
        fill_totals = {"total": 0, "input": 0, "input_cache": 0, "output": 0}
        duration = 0
        incomplete_runs = 0
        for run in runs:
            for key in totals:
                totals[key] += run["translation"][key]
                fill_totals[key] += run["fill"][key]
            duration += run["duration_seconds"]
            if not run["completed"]:
                incomplete_runs += 1
        return {
            "translation": totals,
            "fill": fill_totals,
            "duration_seconds": duration,
            "total_runs": len(runs),
            "incomplete_runs": incomplete_runs,
        }

    def _fill_entry(self, data: dict, translation_llm, fill_llm, elapsed: float, completed: bool) -> None:
        if self._run_index is None:
            return
        entry = data[self._book_name][self._run_index]
        entry["completed"] = completed
        entry["duration_seconds"] = int(elapsed)
        entry["translation"] = {
            "total": translation_llm.total_tokens,
            "input": translation_llm.input_tokens,
            "input_cache": translation_llm.input_cache_tokens,
            "output": translation_llm.output_tokens,
        }
        entry["fill"] = {
            "total": fill_llm.total_tokens,
            "input": fill_llm.input_tokens,
            "input_cache": fill_llm.input_cache_tokens,
            "output": fill_llm.output_tokens,
        }

    def _load(self) -> dict:
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(self._path)
