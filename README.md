# System Strength Assessment Workflow

This repository contains a system strength workflow that can now be run as a Windows desktop GUI application. The workflow calculates system strength metrics, generates geographic visualizations, and builds combined HTML display pages.

## Workflow Scripts

- [scripts/run_workflow.py](scripts/run_workflow.py)
  - Driver script used by both CLI and GUI.
  - Runs the workflow scripts in this order:
    1. [src/system_strength_tool/extract_metric.py](src/system_strength_tool/extract_metric.py)
    2. [src/system_strength_tool/map_metric.py](src/system_strength_tool/map_metric.py)
    3. [src/system_strength_tool/create_display.py](src/system_strength_tool/create_display.py)
  - Iterates over two keyword labels in code: GFL and GFM, then compares the two.
- [scripts/run_gui.py](scripts/run_gui.py)
  - Windows-friendly Tkinter desktop app.
  - Lets you select analysis, mode, and metric, then run the workflow with live logs.
  - Can open output folder and latest comparison viewer directly.
- [src/system_strength_tool/extract_metric.py](src/system_strength_tool/extract_metric.py)
  - Runs PSS/E dynamic simulations and extracts SCMVA/SCR results.
  - Writes:
    - SCR_Results_{keyword}.xlsx
    - raw_out_data/dynamic_simulation_results_{keyword}.xlsx
    - raw_out_data/postprocessed_dynamic_simulation_results_{keyword}.xlsx
- [src/system_strength_tool/map_metric.py](src/system_strength_tool/map_metric.py)
  - Reads SCR_Results_{keyword}.xlsx.
  - Generates per-case map HTML files in htmls_{keyword}/.
- [src/system_strength_tool/create_display.py](src/system_strength_tool/create_display.py)
  - Reads generated map files from htmls_{keyword}/.
  - Creates htmls_{keyword}/SCR_All_Grid_{keyword}.html.

## Data Inputs

- [model_data](model_data)
  - SAV and DYR model files used by the extraction step.
  - Bus GIS workbook required by the mapping step:
    - model_data/WECC_Bus_GIS.xlsx

## Required Naming Conventions

### Case File Naming
The workflow automatically determines the output directory name from the case file. Case files should follow this naming pattern:

- **WECC cases**: `WECC240_*.sav` → Output folder: `output_WECC240/`
- **Maui cases**: `Maui*.sav` → Output folder: `output_Maui/`
- **Other cases**: `{any_name}.sav` → Output folder: `output_{first_part_before_underscore}/`

For example:
- `WECC240_UPV_v04.sav` → Creates `output_WECC240/`
- `Maui24_DM_r8.sav` → Creates `output_Maui24/`

### Bus Location File
The workflow uses a bus GIS workbook for map generation. The file is automatically selected based on the case filename:

- **WECC cases**: Uses `model_data/WECC_Bus_GIS.xlsx`
- **Maui cases**: Uses `model_data/Maui_Bus_GIS.xlsx` (if available, falls back to WECC_Bus_GIS.xlsx)
- **Other cases**: Uses `model_data/WECC_Bus_GIS.xlsx` (default fallback)

### Input File Locations
Input files (case `.sav`, sequence `.seq`, and dynamics `.dyr` files) can be located anywhere on your system. The GUI file browser or CLI arguments accept absolute or relative paths. However:
- Model data files in `src/system_strength_tool/model_data/` must remain in that location
- Do not move the `model_data` folder or rename its contents

## Requirements

- Python 3.x
- pandas
- numpy
- plotly
- xlsxwriter
- PSS/E version 36.5.0+ (and associated python libraries)

## Run (Windows GUI)

From the repository root:

```powershell
py scripts\run_gui.py
```

In the GUI:
1. Select `analysis`, `mode`, and `metric`.
2. Optional: enable extraction if you want to rerun PSS/E metric extraction.
3. Click **Run Workflow**.
4. Use **Open Compare Viewer** after completion.

## Windows Launcher (Desktop and Start Menu)

You can launch the GUI without opening a terminal.

1. Script launcher file:
  - `NetStrength GUI.cmd`
2. Create Desktop and Start Menu shortcuts:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_launcher.ps1
```

This creates `NetStrength.lnk` on your Desktop and Start Menu.

Icon behavior:
- If the shortcut target is an EXE, Windows uses the icon embedded in that EXE by default.
- If the shortcut target is the script launcher (`NetStrength GUI.cmd`), the installer uses `assets/NetStrength.ico` when present.

By default, the installer uses `-TargetType auto`:
- prefers `dist/NetStrength.exe` when present (cleaner app-like pinning)
- falls back to `NetStrength GUI.cmd` if no exe exists

Optional: target a launcher executable instead of the `.cmd` file:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_launcher.ps1 -TargetType exe
```

## Optional Slim Executable Launcher

This builds a small windowed launcher executable that starts `scripts/run_gui.py` using your local Python installation.

Build default (onedir):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_slim_launcher_exe.ps1
```

Build one-file variant:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_slim_launcher_exe.ps1 -OneFile
```

Output:
- Onedir: `dist/NetStrength/NetStrength.exe`
- Onefile: `dist/NetStrength.exe`

## Run (CLI)

From the repository root:

```powershell
py scripts\run_workflow.py --analysis static --mode evolution --metric SCR
```

To include extraction:

```powershell
py scripts\run_workflow.py --analysis static --mode evolution --metric SCR --extract
```

To launch the GUI via workflow script:

```powershell
py scripts\run_workflow.py --gui
```

## Current Behavior Notes

- The workflow always generates GFL, GFM, and COMPARE views.
- Extraction is optional in the driver and GUI because it can be slow and depends on local PSS/E availability.