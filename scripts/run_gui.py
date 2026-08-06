"""Windows-friendly GUI for the system strength workflow."""

from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk

from PIL import Image, ImageTk

from run_workflow import PROJECT_ROOT, SRC_DIR, WorkflowCancelled, run_workflow


def _find_logo_path() -> Path | None:
    """Return the first available logo path near the project root."""
    candidates = [
        PROJECT_ROOT / "assets" / "netstrength_logo.png",
        PROJECT_ROOT / "assets" / "NetStrength_logo.png",
        PROJECT_ROOT / "NetStrength_logo.png",
        PROJECT_ROOT.parent / "NetStrength_logo.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _find_window_icon_paths() -> tuple[Path | None, Path | None]:
    """Return preferred ICO and PNG icon candidates for the app window icon."""
    ico_candidates = [
        PROJECT_ROOT / "assets" / "NetStrength.ico",
        PROJECT_ROOT / "assets" / "netstrength.ico",
    ]
    png_candidates = [
        PROJECT_ROOT / "assets" / "NetStrength_icon.png",
        PROJECT_ROOT / "assets" / "netstrength_icon.png",
        PROJECT_ROOT / "assets" / "NetStrength_logo.png",
        PROJECT_ROOT / "assets" / "netstrength_logo.png",
    ]

    ico_path = next((path for path in ico_candidates if path.exists()), None)
    png_path = next((path for path in png_candidates if path.exists()), None)
    return ico_path, png_path


class WorkflowApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        ico_path, png_path = _find_window_icon_paths()
        if ico_path is not None:
            self.iconbitmap(str(ico_path))
        elif png_path is not None:
            # Fallback path when ICO has not been generated yet.
            self._window_icon_photo = tk.PhotoImage(file=str(png_path))
            self.iconphoto(True, self._window_icon_photo)
        self.title("NetStrength")
        self.geometry("980x700")
        self.minsize(860, 620)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event: threading.Event | None = None

        self.analysis_var = tk.StringVar(value="static")
        self.mode_var = tk.StringVar(value="snapshot")
        self.metric_var = tk.StringVar(value="NSCR")
        self.scope_var = tk.StringVar(value="control-neutral")
        self.current_limit_var = tk.StringVar(value="1.11")
        self.case_file_var = tk.StringVar(value="")
        self.seq_file_var = tk.StringVar(value="")
        self.dyr_file_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.analysis_var.trace_add("write", self._on_viewer_selection_changed)
        self.mode_var.trace_add("write", self._on_viewer_selection_changed)
        self.metric_var.trace_add("write", self._on_viewer_selection_changed)
        self.analysis_var.trace_add("write", self._on_input_selection_changed)
        self.scope_var.trace_add("write", self._on_input_selection_changed)
        self.case_file_var.trace_add("write", self._on_case_file_changed)
        self.analysis_var.trace_add("write", self._on_analysis_changed)
        self._on_analysis_changed()  # Apply initial state for default analysis
        self._refresh_viewer_buttons()
        self._apply_input_rules()
        self.after(120, self._drain_log_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#f5f5f5')
        style.configure('TFrame', background='#f5f5f5')
        style.configure('TLabel', background='#f5f5f5')
        style.configure('TLabelframe', background='#f5f5f5')
        style.configure('Green.TButton', foreground='#f3f3f3', background='#1b8f3a')
        style.map('Green.TButton', 
            background=[('pressed', '#156f2c'), ('active', '#24a148'), ('disabled', '#b7d9c2')], 
            foreground=[('disabled', '#f3f3f3')]
        )
        style.configure('Red.TButton', foreground='#f3f3f3', background='#d32f2f')
        style.map('Red.TButton',
            background=[('pressed', '#c62828'), ('active', '#e53935'), ('disabled', "#595858")],
            foreground=[('disabled', '#f3f3f3')]
        )

        header = ttk.Frame(self, padding=(16, 14))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        # Title and subtitle on the left
        left_frame = ttk.Frame(header)
        left_frame.grid(row=0, column=0, sticky="ew")
        left_frame.columnconfigure(0, weight=1)

        title = ttk.Label(left_frame, text="NetStrength: System Strength Assessment", font=("Segoe UI", 15, "bold"))
        title.grid(row=0, column=0, sticky="w")

        subtitle = ttk.Label(
            left_frame,
            text="Extract system strength metrics from your system in one step. Visualize them in two.",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 10))

        # Logo on the right
        try:
            logo_path = _find_logo_path()
            if logo_path is not None:
                logo_img = Image.open(logo_path)
                logo_img.thumbnail((150, 150), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(logo_img)
                logo_label = ttk.Label(header, image=self.logo_photo)
                logo_label.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(20, 0))
        except Exception as e:
            print(f"Warning: Could not load logo image: {e}")

        form = ttk.LabelFrame(header, text="Configuration", padding=(10, 8))
        form.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        form.columnconfigure(0, weight=0)
        form.columnconfigure(1, weight=0)
        form.columnconfigure(2, weight=0)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="Analysis").grid(row=0, column=0, sticky="w", padx=(0, 8))
        analysis_combo = ttk.Combobox(
            form,
            textvariable=self.analysis_var,
            values=["static", "dynamic"],
            width=12,
            state="readonly",
        )
        analysis_combo.grid(row=1, column=0, sticky="w", padx=(0, 14))

        ttk.Label(form, text="Mode").grid(row=0, column=1, sticky="w", padx=(0, 8))
        mode_combo = ttk.Combobox(
            form,
            textvariable=self.mode_var,
            values=["snapshot", "evolution"],
            width=12,
            state="readonly",
        )
        mode_combo.grid(row=1, column=1, sticky="w", padx=(0, 14))

        ttk.Label(form, text="Metric").grid(row=0, column=2, sticky="w", padx=(0, 8))
        metric_combo = ttk.Combobox(
            form,
            textvariable=self.metric_var,
            values=["SCR", "NSCR"],
            width=12,
            state="readonly",
        )
        metric_combo.grid(row=1, column=2, sticky="w", padx=(0, 14))

        ttk.Label(form, text="IBR Type").grid(row=0, column=3, sticky="w", padx=(0, 8))
        self.scope_combo = ttk.Combobox(
            form,
            textvariable=self.scope_var,
            values=["control-neutral"],
            width=14,
            state="readonly",
        )
        self.scope_combo.grid(row=1, column=3, sticky="w", padx=(0, 14))

        ttk.Label(form, text="Default Current Limit (pu)").grid(row=0, column=4, sticky="w", pady=(8, 0), padx=(0, 8))
        self.current_limit_entry = ttk.Entry(form, textvariable=self.current_limit_var, width=12)
        self.current_limit_entry.grid(row=0, column=5, sticky="w", pady=(8, 0), padx=(0, 14))

        files_frame = ttk.LabelFrame(header, text="Input Files", padding=(10, 8))
        files_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        files_frame.columnconfigure(1, weight=1)

        ttk.Label(files_frame, text="Case (.sav)").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        self.case_file_entry = ttk.Entry(files_frame, textvariable=self.case_file_var)
        self.case_file_entry.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        self.case_file_button = ttk.Button(
            files_frame,
            text="Browse",
            command=lambda: self._browse_file(self.case_file_var, [("SAV files", "*.sav"), ("All files", "*.*")]),
        )
        self.case_file_button.grid(row=0, column=2, padx=(8, 0), pady=(0, 6))

        ttk.Label(files_frame, text="SEQ (.seq) static").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        self.seq_file_entry = ttk.Entry(files_frame, textvariable=self.seq_file_var)
        self.seq_file_entry.grid(row=1, column=1, sticky="ew", pady=(0, 6))
        self.seq_file_button = ttk.Button(
            files_frame,
            text="Browse",
            command=lambda: self._browse_file(self.seq_file_var, [("SEQ files", "*.seq"), ("All files", "*.*")]),
        )
        self.seq_file_button.grid(row=1, column=2, padx=(8, 0), pady=(0, 6))

        ttk.Label(files_frame, text="DYR (.dyr) dynamic").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        self.dyr_file_entry = ttk.Entry(files_frame, textvariable=self.dyr_file_var)
        self.dyr_file_entry.grid(row=2, column=1, sticky="ew", pady=(0, 6))
        self.dyr_file_button = ttk.Button(
            files_frame,
            text="Browse",
            command=lambda: self._browse_file(self.dyr_file_var, [("DYR files", "*.dyr"), ("All files", "*.*")]),
        )
        self.dyr_file_button.grid(row=2, column=2, padx=(8, 0), pady=(0, 6))

        buttons = ttk.LabelFrame(header, text="Actions", padding=(10, 8))
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)
        buttons.columnconfigure(3, weight=1)

        self.run_extraction_button = ttk.Button(buttons, text="Run Extraction", command=self._on_run_extraction, style="Green.TButton")
        self.run_extraction_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.run_mapping_button = ttk.Button(buttons, text="Run Mapping", command=self._on_run_mapping, style="Green.TButton")
        self.run_mapping_button.grid(row=0, column=1, sticky="ew", padx=(0, 6))

        self.cancel_button = ttk.Button(buttons, text="Cancel Workflow", command=self._on_cancel, state="disabled", style="Red.TButton")
        self.cancel_button.grid(row=0, column=2, sticky="ew", padx=(0, 6))

        self.open_output_button = ttk.Button(
            buttons,
            text="Open Output Folder",
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_output_button.grid(row=0, column=3, sticky="ew")

        self.open_gfl_viewer_button = ttk.Button(
            buttons,
            text="Open GFL Viewer",
            command=self._open_gfl_viewer,
            state="disabled",
        )
        self.open_gfl_viewer_button.grid(row=1, column=0, sticky="ew", pady=(6, 0), padx=(0, 6))

        self.open_gfm_viewer_button = ttk.Button(
            buttons,
            text="Open GFM Viewer",
            command=self._open_gfm_viewer,
            state="disabled",
        )
        self.open_gfm_viewer_button.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(0, 6))

        self.open_viewer_button = ttk.Button(
            buttons,
            text="Open Compare Viewer",
            command=self._open_latest_viewer,
            state="disabled",
        )
        self.open_viewer_button.grid(row=1, column=2, columnspan=2, sticky="ew", pady=(6, 0))

        body = ttk.Frame(self, padding=(16, 0, 16, 12))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            body,
            wrap="word",
            height=28,
            font=("Courier New", 10),
            bg="#0b1a2a",
            fg="#eaf2ff",
            insertbackground="#eaf2ff",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")
        
        # Configure text tags for color-coded messages
        self.log_text.tag_config("success", foreground="#00CC00")  # Bright green
        self.log_text.tag_config("warning", foreground="#FFEA00")  # Bright yellow
        self.log_text.tag_config("error", foreground="#FF5555")    # Bright red
        self.log_text.tag_config("info", foreground="#87CEEB")     # Sky blue
        self.log_text.tag_config("separator", foreground="#808080") # Gray

        scroll = ttk.Scrollbar(body, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        footer = ttk.Frame(self, padding=(16, 0, 16, 14))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        status = ttk.Label(footer, textvariable=self.status_var)
        status.grid(row=0, column=1, sticky="e")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        
        # Auto-detect message type based on keywords
        msg_lower = message.lower()
        if any(keyword in msg_lower for keyword in ["success", "finished", "completed", "saved"]):
            tag = "success"
        elif any(keyword in msg_lower for keyword in ["error", "failed", "exception", "traceback"]):
            tag = "error"
        elif any(keyword in msg_lower for keyword in ["warning", "cancell"]):
            tag = "warning"
        elif message.startswith("-"):
            tag = "separator"
        else:
            tag = "info"
        
        self.log_text.insert("end", message + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log_callback(self, message: str) -> None:
        self.log_queue.put(message)

    def _drain_log_queue(self) -> None:
        while not self.log_queue.empty():
            self._append_log(self.log_queue.get())
        self.after(120, self._drain_log_queue)

    def _set_running_state(self, running: bool) -> None:
        if running:
            self.run_extraction_button.configure(state="disabled")
            self.run_mapping_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self.status_var.set("Running")
            self.progress.start(10)
        else:
            self.run_extraction_button.configure(state="normal")
            self.run_mapping_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.progress.stop()

    def _selected_scope(self) -> str:
        scope = self.scope_var.get().strip().lower()
        return scope if scope in {"gfl & gfm", "gfl", "gfm", "compare", "control-neutral"} else "gfl & gfm"

    def _set_input_enabled(self, entry: ttk.Entry, button: ttk.Button, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        entry.configure(state=state)
        button.configure(state=state)

    def _apply_input_rules(self) -> None:
        scope = self._selected_scope()
        analysis = self.analysis_var.get().strip().lower()
        extraction_runs = scope in {"gfl & gfm", "gfl", "gfm", "control-neutral"}

        enable_case = extraction_runs
        enable_seq = extraction_runs and analysis == "static"
        enable_current_limit = extraction_runs and analysis == "static"
        enable_dyr = extraction_runs and analysis == "dynamic"

        self._set_input_enabled(self.case_file_entry, self.case_file_button, enable_case)
        self._set_input_enabled(self.seq_file_entry, self.seq_file_button, enable_seq)
        self.current_limit_entry.configure(state="normal" if enable_current_limit else "disabled")
        self._set_input_enabled(self.dyr_file_entry, self.dyr_file_button, enable_dyr)

    def _on_input_selection_changed(self, *_: object) -> None:
        self._apply_input_rules()

    def _on_analysis_changed(self, *_: object) -> None:
        if self.analysis_var.get().strip().lower() == "static":
            self.scope_combo.configure(values=["control-neutral"])
            self.scope_var.set("control-neutral")
            self.open_gfl_viewer_button.grid_remove()
            self.open_gfm_viewer_button.grid_remove()
            self.open_viewer_button.configure(text="Open Viewer")
            self.open_viewer_button.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        else:
            self.scope_combo.configure(values=["GFL & GFM", "GFL", "GFM", "COMPARE"])
            if self.scope_var.get() == "control-neutral":
                self.scope_var.set("GFL & GFM")
            self.open_gfl_viewer_button.grid(row=1, column=0, sticky="ew", pady=(6, 0), padx=(0, 6))
            self.open_gfm_viewer_button.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(0, 6))
            self.open_viewer_button.configure(text="Open Compare Viewer")
            self.open_viewer_button.grid(row=1, column=2, columnspan=2, sticky="ew", pady=(6, 0))
        self._refresh_viewer_buttons()

    def _browse_file(self, target_var: tk.StringVar, filetypes: list[tuple[str, str]]) -> None:
        model_data_dir = SRC_DIR / "model_data"
        initial = model_data_dir if model_data_dir.is_dir() else PROJECT_ROOT
        selected = filedialog.askopenfilename(title="Select file", filetypes=filetypes, initialdir=str(initial))
        if selected:
            target_var.set(selected)

    def _validate_input_file(self, file_path: str, expected_suffix: str, label: str) -> str:
        candidate = Path(file_path).expanduser()
        if not candidate.is_file():
            raise ValueError(f"{label} file was not found: {candidate}")
        if candidate.suffix.lower() != expected_suffix:
            raise ValueError(f"{label} must be a {expected_suffix} file.")
        return str(candidate.resolve())

    def _refresh_viewer_buttons(self) -> None:
        analysis = self.analysis_var.get().strip().lower()
        if analysis == "static":
            self.open_viewer_button.configure(state="normal" if self._viewer_path("CONTROL-NEUTRAL").exists() else "disabled")
        else:
            self.open_viewer_button.configure(state="normal" if self._viewer_path("COMPARE").exists() else "disabled")
            self.open_gfl_viewer_button.configure(state="normal" if self._viewer_path("GFL").exists() else "disabled")
            self.open_gfm_viewer_button.configure(state="normal" if self._viewer_path("GFM").exists() else "disabled")

    def _refresh_output_folder_button(self) -> None:
        case_file = self.case_file_var.get()
        if case_file:
            output_dir = PROJECT_ROOT / f"output_{"_".join(Path(case_file).stem.split('_')[:2])}"
            state = "normal" if output_dir.exists() else "disabled"
        else:
            state = "disabled"
        self.open_output_button.configure(state=state)

    def _on_case_file_changed(self, *_: object) -> None:
        self._refresh_output_folder_button()

    def _on_viewer_selection_changed(self, *_: object) -> None:
        self._refresh_viewer_buttons()

    def _viewer_path(self, keyword: str) -> Path:
        analysis = self.analysis_var.get().strip().lower()
        mode = self.mode_var.get().strip().lower()
        metric = self.metric_var.get().strip().upper()
        case_file = self.case_file_var.get()
        return (
            PROJECT_ROOT
            /f"output_{"_".join(Path(case_file).stem.split('_')[:2])}"
            / f"{analysis}_analysis"
            / mode
            / keyword
            / f"{metric}_htmls"
            / "Strength_All_Grid.html"
        )

    def _on_run_extraction(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Workflow in progress", "Please wait for the current process to finish.")
            return
        self._run_workflow(include_extract=True, include_mapping=False)

    def _on_run_mapping(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Workflow in progress", "Please wait for the current process to finish.")
            return
        self._run_workflow(include_extract=False, include_mapping=True)

    def _run_workflow(self, include_extract: bool, include_mapping: bool) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Workflow in progress", "Please wait for the current process to finish.")
            return

        analysis = self.analysis_var.get().strip().lower()
        mode = self.mode_var.get().strip().lower()
        metric = self.metric_var.get().strip().upper()

        if analysis not in {"static", "dynamic"}:
            messagebox.showerror("Invalid analysis", "Analysis must be static or dynamic.")
            return

        if mode not in {"snapshot", "evolution"}:
            messagebox.showerror("Invalid mode", "Mode must be snapshot or evolution.")
            return

        if not metric:
            messagebox.showerror("Invalid metric", "Metric cannot be empty.")
            return

        scope = self._selected_scope()
        
        case_file: str | None = None
        seq_file: str | None = None
        dyr_file: str | None = None
        current_limit: float | None = None

        try:
            extraction_runs = include_extract and scope in {"gfl & gfm", "gfl", "gfm", "control-neutral"}
            case_file = self._validate_input_file(self.case_file_var.get().strip(), ".sav", "Case (.sav)")
            if extraction_runs:
                if analysis == "static":
                    seq_file = self._validate_input_file(self.seq_file_var.get().strip(), ".seq", "SEQ (.seq)")
                    try:
                        current_limit = float(self.current_limit_var.get().strip())
                    except ValueError as exc:
                        raise ValueError("Default current limit must be a numeric value.") from exc
                    if current_limit <= 0:
                        raise ValueError("Default current limit must be greater than 0.")
                else:
                    dyr_file = self._validate_input_file(
                        self.dyr_file_var.get().strip(),
                        ".dyr",
                        "DYR (.dyr)",
                    )
        except ValueError as exc:
            messagebox.showerror("Invalid input file", str(exc))
            return

        self.cancel_event = threading.Event()
        self._set_running_state(True)
        self._append_log("-" * 80)
        self._append_log(
            f"Requested run: analysis={analysis}, mode={mode}, metric={metric}, "
            f"scope={scope}, extract={include_extract}, mapping={include_mapping}"
        )

        self.worker = threading.Thread(
            target=self._run_workflow_worker,
            args=(
                analysis,
                mode,
                metric,
                scope,
                include_extract,
                include_mapping,
                case_file,
                seq_file,
                dyr_file,
                current_limit,
                self.cancel_event,
            ),
            daemon=True,
        )
        self.worker.start()

    def _on_cancel(self) -> None:
        if self.cancel_event is None or not (self.worker and self.worker.is_alive()):
            return

        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set("Cancelling workflow...")
        self._append_log("Cancellation requested.")

    def _run_workflow_worker(
        self,
        analysis: str,
        mode: str,
        metric: str,
        scope: str,
        include_extract: bool,
        include_mapping: bool,
        case_file: str | None,
        seq_file: str | None,
        dyr_file: str | None,
        current_limit: float | None,
        cancel_event: threading.Event,
    ) -> None:
        try:
            compare_path, gfl_path, gfm_path = run_workflow(
                analysis=analysis,
                mode=mode,
                metric=metric,
                scope=scope,
                include_extract=include_extract,
                include_mapping=include_mapping,
                case_file=case_file,
                seq_file=seq_file,
                dyr_file=dyr_file,
                current_limit=current_limit,
                cancel_event=cancel_event,
                log=self._log_callback,
            )
            for label, path in (("COMPARE", compare_path), ("GFL", gfl_path), ("GFM", gfm_path)):
                if path is not None:
                    self.log_queue.put(f"{label} viewer path: {path}")
            self.log_queue.put("Workflow finished successfully.")
            self.after(0, self._on_run_success)
        except WorkflowCancelled:
            self.log_queue.put("Workflow cancelled.")
            self.after(0, self._on_run_cancelled)
        except Exception as exc:  # pragma: no cover - runtime safety path
            self.log_queue.put("Workflow failed.")
            self.log_queue.put(str(exc))
            self.log_queue.put(traceback.format_exc())
            error_text = str(exc)
            self.after(0, lambda message=error_text: self._on_run_error(message))

    def _on_run_success(self) -> None:
        self._set_running_state(False)
        self.status_var.set("Completed")
        self.cancel_event = None
        self._refresh_viewer_buttons()
        self._refresh_output_folder_button()

    def _on_run_error(self, error_text: str) -> None:
        self._set_running_state(False)
        self.status_var.set("Failed")
        self.cancel_event = None
        messagebox.showerror("Workflow failed", error_text)

    def _on_run_cancelled(self) -> None:
        self._set_running_state(False)
        self.status_var.set("Cancelled")
        self.cancel_event = None

    def _open_latest_viewer(self) -> None:
        analysis = self.analysis_var.get().strip().lower()
        keyword = "CONTROL-NEUTRAL" if analysis == "static" else "COMPARE"
        viewer_path = self._viewer_path(keyword)
        if viewer_path.exists():
            webbrowser.open(viewer_path.resolve().as_uri())
        else:
            messagebox.showinfo(
                "Viewer not found",
                f"No viewer found for the current selection:\n{viewer_path}",
            )

    def _open_gfl_viewer(self) -> None:
        viewer_path = self._viewer_path("GFL")
        if viewer_path.exists():
            webbrowser.open(viewer_path.resolve().as_uri())
        else:
            messagebox.showinfo(
                "Viewer not found",
                f"No GFL viewer found for the current selection:\n{viewer_path}",
            )

    def _open_gfm_viewer(self) -> None:
        viewer_path = self._viewer_path("GFM")
        if viewer_path.exists():
            webbrowser.open(viewer_path.resolve().as_uri())
        else:
            messagebox.showinfo(
                "Viewer not found",
                f"No GFM viewer found for the current selection:\n{viewer_path}",
            )

    def _open_output_folder(self) -> None:
        case_file = self.case_file_var.get()
        output_dir = PROJECT_ROOT / f"output_{"_".join(Path(case_file).stem.split('_')[:2])}"
        try:
            # Windows Explorer integration.
            import os

            os.startfile(str(output_dir))
        except Exception:
            webbrowser.open(output_dir.resolve().as_uri())


def launch_app() -> None:
    app = WorkflowApp()
    app.mainloop()


if __name__ == "__main__":
    launch_app()
