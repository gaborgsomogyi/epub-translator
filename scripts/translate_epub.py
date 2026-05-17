import argparse
import logging
import os
import sys
import time
import threading

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from pathlib import Path

from tqdm import tqdm

from epub_translator import FillFailedEvent, SubmitKind, translate
from scripts.stats import StatsTracker
from scripts.utils import load_llm, read_and_clean_temp


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate EPUB files to target language")
    parser.add_argument("source_path", type=str, help="Path to the source EPUB file")
    parser.add_argument(
        "-l", "--lan", type=str, default="Chinese", help="Target language for translation (default: Chinese)"
    )
    parser.add_argument(
        "-m", "--mode", type=str, default="replace",
        choices=["replace", "append_block", "append_text"],
        help="Translation mode: replace (default), append_block (bilingual), append_text (inline bilingual)"
    )
    args = parser.parse_args()
    source_path = Path(args.source_path)

    if not source_path.exists():
        print(f"Error: Source file '{source_path}' does not exist")
        sys.exit(1)

    target_language = args.lan
    submit_mode = {
        "replace": SubmitKind.REPLACE,
        "append_block": SubmitKind.APPEND_BLOCK,
        "append_text": SubmitKind.APPEND_TEXT,
    }[args.mode]

    temp_path = read_and_clean_temp()
    translation_llm, fill_llm = load_llm(
        cache_path=Path(__file__).parent / ".." / "cache",
        log_dir_path=temp_path / "logs",
    )
    log_file = temp_path / "fill_errors.log"
    logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s %(message)s")
    fill_logger = logging.getLogger("fill")

    cache_path = Path(__file__).parent / ".." / "cache"
    cache_path.mkdir(parents=True, exist_ok=True)
    stats = StatsTracker(cache_path / "stats.json", source_path.name)
    stats.start_run()

    fill_retry_count = 0
    fill_retry_lock = threading.Lock()

    start_time = time.time()
    with tqdm(total=100, desc="Translating", unit="%", bar_format="{l_bar}{bar}| {n:.1f}/{total:.0f}% {postfix}") as pbar:
        pbar.set_postfix({"fill retries": 0}, refresh=False)
        last_progress = 0.0

        def on_progress(progress: float) -> None:
            nonlocal last_progress
            increment = (progress - last_progress) * 100
            pbar.update(increment)
            last_progress = progress
            stats.update(translation_llm, fill_llm, time.time() - start_time)

        def on_fill_failed(event: FillFailedEvent):
            nonlocal fill_retry_count
            fill_logger.info("Retry %d validation failed:\n%s", event.retried_count, event.error_message)
            if event.over_maximum_retries:
                fill_logger.warning("Maximum retries reached without successful XML filling.")
            with fill_retry_lock:
                fill_retry_count += 1
                pbar.set_postfix({"fill retries": fill_retry_count}, refresh=True)

        try:
            translate(
                translation_llm=translation_llm,
                fill_llm=fill_llm,
                concurrency=4,
                target_language=target_language,
                submit=submit_mode,
                source_path=source_path,
                target_path=temp_path / "translated.epub",
                on_progress=on_progress,
                on_fill_failed=on_fill_failed,
            )
        except KeyboardInterrupt:
            stats.update(translation_llm, fill_llm, time.time() - start_time, force=True)
            print("\nTranslation interrupted.")
            os._exit(130)
        on_progress(1.0)

    elapsed = time.time() - start_time
    stats.complete(translation_llm, fill_llm, elapsed)
    acc = stats.accumulated()

    def fmt_time(seconds: int) -> str:
        h, r = divmod(seconds, 3600)
        m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def print_tokens(label: str, t: dict) -> None:
        print(f"\n{label}:")
        print(f"  Total tokens:       {t['total']:,}")
        print(f"  Input tokens:       {t['input']:,}")
        print(f"  Input cache tokens: {t['input_cache']:,}")
        print(f"  Output tokens:      {t['output']:,}")

    print("\n" + "=" * 50)
    print("This Session")
    print("=" * 50)
    print_tokens("Translation LLM", {
        "total": translation_llm.total_tokens,
        "input": translation_llm.input_tokens,
        "input_cache": translation_llm.input_cache_tokens,
        "output": translation_llm.output_tokens,
    })
    print_tokens("Fill LLM", {
        "total": fill_llm.total_tokens,
        "input": fill_llm.input_tokens,
        "input_cache": fill_llm.input_cache_tokens,
        "output": fill_llm.output_tokens,
    })
    session_total = translation_llm.total_tokens + fill_llm.total_tokens
    session_input = translation_llm.input_tokens + fill_llm.input_tokens
    session_cache = translation_llm.input_cache_tokens + fill_llm.input_cache_tokens
    session_output = translation_llm.output_tokens + fill_llm.output_tokens
    print_tokens("Combined", {"total": session_total, "input": session_input, "input_cache": session_cache, "output": session_output})
    print(f"\n  Time: {fmt_time(int(elapsed))}")

    acc_t = acc["translation"]
    acc_f = acc["fill"]
    acc_total = acc_t["total"] + acc_f["total"]
    acc_input = acc_t["input"] + acc_f["input"]
    acc_cache = acc_t["input_cache"] + acc_f["input_cache"]
    acc_output = acc_t["output"] + acc_f["output"]
    incomplete_note = f"  ({acc['incomplete_runs']} incomplete)" if acc["incomplete_runs"] else ""

    print("\n" + "=" * 50)
    print(f"All Runs ({acc['total_runs']} total{incomplete_note})")
    print("=" * 50)
    print_tokens("Translation LLM", acc_t)
    print_tokens("Fill LLM", acc_f)
    print_tokens("Combined", {"total": acc_total, "input": acc_input, "input_cache": acc_cache, "output": acc_output})
    print(f"\n  Time: {fmt_time(acc['duration_seconds'])}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
