"""Run the system strength workflow from CLI or GUI."""

from __future__ import annotations

import argparse
import queue
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable
import time


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_DIR = PROJECT_ROOT / "src" / "system_strength_tool"
EXTRACT_SCRIPT = SRC_DIR / "extract_metric.py"
MAP_SCRIPT = SRC_DIR / "map_metric.py"
DISPLAY_SCRIPT = SRC_DIR / "create_display.py"

LogCallback = Callable[[str], None]

def print_end_time(start_time):
    # Record the ending time
    end_time = time.perf_counter()
    
    # Calculate and display the duration
    elapsed_time = end_time - start_time
    print(f"Total workflow time: {elapsed_time:.6f} seconds")
    return

class WorkflowCancelled(RuntimeError):
    """Raised when the user requests a cooperative workflow cancel."""


def _default_log(message: str) -> None:
    print(message)


def _terminate_process(process: subprocess.Popen[str], script_name: str, log: LogCallback) -> None:
    if process.poll() is not None:
        return

    log(f"Cancellation requested during {script_name}. Terminating current step...")
    try:
        process.terminate()
    except (ProcessLookupError, OSError) as exc:
        log(f"{script_name} was already stopping: {exc}")
        return

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except (ProcessLookupError, OSError) as exc:
            log(f"{script_name} could not be force-killed cleanly: {exc}")
            return
        process.wait()


def run_script(
    script_path: Path,
    keyword: str,
    analysis: str,
    mode: str,
    metric: str,
    case_file: str | None = None,
    seq_file: str | None = None,
    dyr_file: str | None = None,
    current_limit: float | None = None,
    cancel_event: threading.Event | None = None,
    log: LogCallback = _default_log,
) -> None:
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"Required script not found: {script_path}")

    if cancel_event is not None and cancel_event.is_set():
        raise WorkflowCancelled("Workflow cancelled before starting the next step.")

    script_name = os.path.basename(script_path)
    cmd = [
        sys.executable,
        str(script_path),
        "--keyword",
        keyword,
        "--analysis",
        analysis,
        "--mode",
        mode,
        "--metric",
        metric,
    ]
    if case_file:
        cmd.extend(["--case-file", case_file])
    if seq_file:
        cmd.extend(["--seq-file", seq_file])
    if dyr_file:
        cmd.extend(["--dyr-file", dyr_file])
    if current_limit is not None:
        cmd.extend(["--current-limit", str(current_limit)])

    log(
        f"Running: {script_name} "
        f"(keyword={keyword}, analysis={analysis}, mode={mode}, metric={metric})"
    )

    process = subprocess.Popen(
        cmd,
        cwd=str(SRC_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    assert process.stdout is not None

    output_queue: queue.Queue[str | None] = queue.Queue()

    def _read_output() -> None:
        for line in process.stdout:
            output_queue.put(line)
        output_queue.put(None)

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()

    reader_finished = False
    while True:
        if cancel_event is not None and cancel_event.is_set():
            _terminate_process(process, script_name, log)
            reader.join(timeout=5)
            raise WorkflowCancelled("Workflow cancelled by the user.")

        try:
            line = output_queue.get(timeout=0.1)
        except queue.Empty:
            if reader_finished and process.poll() is not None:
                break
            continue

        if line is None:
            reader_finished = True
            if process.poll() is not None:
                break
            continue

        line = line.rstrip()
        if line:
            log(f"[{script_name}] {line}")

        if reader_finished and process.poll() is not None and output_queue.empty():
            break

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"{script_name} failed with exit code {return_code}.")

    log(f"Completed: {script_name}\n")


def run_workflow(
    analysis: str,
    mode: str,
    metric: str,
    scope: str = "GFL & GFM",
    include_extract: bool = True,
    include_mapping: bool = True,
    case_file: str | None = None,
    seq_file: str | None = None,
    dyr_file: str | None = None,
    current_limit: float | None = None,
    cancel_event: threading.Event | None = None,
    log: LogCallback = _default_log,
) -> tuple[Path | None, Path | None, Path | None]:
    
    global OUTPUT_DIR
    OUTPUT_DIR = PROJECT_ROOT / f"output_{Path(case_file).stem.split('_')[0]}"

    start_time = time.perf_counter()

    scope_name = scope.strip().lower()
    if scope_name not in {"gfl & gfm", "gfl", "gfm", "compare", "control-neutral"}:
        raise ValueError(f"scope must be one of: GFL & GFM, GFL, GFM, COMPARE, control-neutral. Scope is: {scope_name}")

    default_extract = scope_name in {"gfl & gfm", "gfl", "gfm", "control-neutral"}
    should_extract = default_extract and include_extract
    should_map = include_mapping

    selected_keywords = (
        ["GFL", "GFM"]
        if scope_name == "gfl & gfm"
        else [scope_name.upper()]
        if scope_name in {"gfl", "gfm", "compare", "control-neutral"}
        else []
    )

    if should_extract:
        if not case_file:
            raise ValueError("A .sav case file is required for GFL & GFM, GFL, and GFM workflows.")
        if analysis == "static":
            if not seq_file:
                raise ValueError("A .seq file is required for static analysis when extraction runs.")
        elif analysis == "dynamic":
            if not dyr_file:
                raise ValueError("A .dyr file is required for dynamic analysis when extraction runs.")

    for keyword in selected_keywords:
        if should_extract:
            run_script(
                EXTRACT_SCRIPT,
                keyword,
                analysis,
                mode,
                metric,
                case_file=case_file,
                seq_file=seq_file if analysis == "static" else None,
                dyr_file=dyr_file if analysis == "dynamic" else None,
                current_limit=current_limit if analysis == "static" else None,
                cancel_event=cancel_event,
                log=log,
            )
        if should_map:
            run_script(
                MAP_SCRIPT,
                keyword,
                analysis,
                mode,
                metric,
                case_file=case_file,
                cancel_event=cancel_event,
                log=log,
            )
            run_script(DISPLAY_SCRIPT, keyword, analysis, mode, metric, case_file=case_file, cancel_event=cancel_event, log=log)

    if should_map and scope_name in {"gfl & gfm", "compare"}:
        # Build maps from per-bus delta metric = GFM - GFL for each penetration level.
        run_script(
            MAP_SCRIPT,
            "COMPARE",
            analysis,
            mode,
            metric,
            case_file=case_file,
            cancel_event=cancel_event,
            log=log,
        )
        run_script(DISPLAY_SCRIPT, "COMPARE", analysis, mode, metric, case_file=case_file, cancel_event=cancel_event, log=log)

    compare_grid_path = (
        OUTPUT_DIR
        / f"{analysis}_analysis"
        / mode
        / "COMPARE"
        / f"{metric}_htmls"
        / "Strength_All_Grid.html"
    )
    gfl_grid_path = (
        OUTPUT_DIR
        / f"{analysis}_analysis"
        / mode
        / "GFL"
        / f"{metric}_htmls"
        / "Strength_All_Grid.html"
    )
    gfm_grid_path = (
        OUTPUT_DIR
        / f"{analysis}_analysis"
        / mode
        / "GFM"
        / f"{metric}_htmls"
        / "Strength_All_Grid.html"
    )
    log("Workflow completed successfully.")
    print_end_time(start_time)
    control_neutral_grid_path = (
        OUTPUT_DIR
        / f"{analysis}_analysis"
        / mode
        / "CONTROL-NEUTRAL"
        / f"{metric}_htmls"
        / "Strength_All_Grid.html"
    )
    if scope_name == "control-neutral":
        return control_neutral_grid_path, None, None
    if scope_name == "gfl":
        return None, gfl_grid_path, None
    if scope_name == "gfm":
        return None, None, gfm_grid_path
    if scope_name == "compare":
        return compare_grid_path, None, None

    return compare_grid_path, gfl_grid_path, gfm_grid_path


def launch_gui() -> None:
    from run_gui import launch_app

    launch_app()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full system strength workflow.")
    parser.add_argument("--analysis", default="static", choices=["static", "dynamic"])
    parser.add_argument("--mode", default="evolution", choices=["snapshot", "evolution"])
    parser.add_argument("--metric", default="SCR", help="Strength metric type to evaluate (e.g., SCR)")
    parser.add_argument(
        "--scope",
        default="GFL & GFM",
        choices=["GFL & GFM", "GFL", "GFM", "COMPARE", "control-neutral"],
        help="Select which workflow branch to run.",
    )
    parser.add_argument("--case-file", help="Path to the starting PSS/E case (.sav).")
    parser.add_argument("--seq-file", help="Path to the sequence data file (.seq) for static extraction.")
    parser.add_argument("--dyr-file", help="Path to the dynamics file (.dyr) for dynamic extraction.")
    parser.add_argument("--current-limit", type=float, help="Default IBR current limit in pu for static extraction.")

    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the desktop GUI application.",
    )
    args = parser.parse_args()

    if args.gui:
        launch_gui()
    else:
        run_workflow(
            analysis=args.analysis,
            mode=args.mode,
            metric=args.metric,
            scope=args.scope,
            case_file=args.case_file,
            seq_file=args.seq_file,
            dyr_file=args.dyr_file,
            current_limit=args.current_limit,
        )

