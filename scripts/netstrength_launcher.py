"""Tiny Windows launcher for the NetStrength GUI.

This script is designed to be frozen into a small windowed executable.
It launches the real GUI script with an existing Python installation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        # When frozen as an EXE, search upward for project markers
        exe_dir = Path(sys.executable).resolve().parent
        current = exe_dir
        while current != current.parent:
            if (current / "pyproject.toml").exists() or (current / "README.md").exists():
                return current
            current = current.parent
        # Fallback: go up 2 levels from exe directory (dist/NetStrength -> project root)
        return exe_dir.parent.parent
    return Path(__file__).resolve().parents[1]


def _show_error(title: str, message: str) -> None:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, message)
    root.destroy()


def _try_launch(command: list[str], cwd: Path) -> tuple[bool, str | None]:
    try:
        subprocess.Popen(command, cwd=str(cwd))
        return True, None
    except FileNotFoundError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        return False, str(exc)


def main() -> int:
    project_root = _project_root()
    gui_script = project_root / "scripts" / "run_gui.py"

    if not gui_script.exists():
        _show_error(
            "NetStrength launcher",
            f"Could not find GUI script:\n{gui_script}\n\n"
            "Place this launcher in the project root or rebuild it there.",
        )
        return 1

    venv_pythonw = project_root / ".venv" / "Scripts" / "pythonw.exe"
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"

    launch_attempts: list[list[str]] = []
    if venv_pythonw.exists():
        launch_attempts.append([str(venv_pythonw), str(gui_script)])
    if venv_python.exists():
        launch_attempts.append([str(venv_python), str(gui_script)])

    launch_attempts.extend(
        [
            ["pyw", "-3", str(gui_script)],
            ["py", "-3", str(gui_script)],
            ["pythonw", str(gui_script)],
            ["python", str(gui_script)],
        ]
    )

    errors: list[str] = []
    for command in launch_attempts:
        ok, err = _try_launch(command, project_root)
        if ok:
            return 0
        if err:
            errors.append(f"{' '.join(command[:2])}: {err}")

    _show_error(
        "NetStrength launcher",
        "Failed to start the GUI with available Python launchers.\n\n"
        "Tried: .venv, pyw, py, pythonw, python\n\n"
        "Install Python or create a .venv in this project, then try again.\n\n"
        f"Details:\n" + "\n".join(errors[:5]),
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
