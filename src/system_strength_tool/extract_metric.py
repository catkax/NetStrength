'''
@date: 25 June 2026
@author: Catherine Kauffman

This code calculates SCMVA and SCR considering full system dynamic behavior 
SCR = SCMVA (of each bus under 3ph fault, with IBRs on that bus disconnected) / 
        Pmax (sum of Pmax of IBRs connected to that bus)
 
input data: 
    1. PSS/E '.raw' files with various penetration of IBRs
    2. '.dyr' file representing all models' dynamic data
        
Note:

'''

import os, sys, argparse
PSSE_LOCATION = r"C:\Program Files\PTI\PSSE36\36.5\PSSBIN"
PSSPY_LOCATION = r"C:\Program Files\PTI\PSSE36\36.5\PSSPY314"
sys.path.append(PSSE_LOCATION)
sys.path.append(PSSPY_LOCATION)
os.environ['PATH'] = os.environ['PATH'] + ';' +  PSSPY_LOCATION + ';' +  PSSE_LOCATION
import psse3605
import psspy
from psspy import _i, _f, _s
import redirect
import dyntools
import glob
import pandas as pd
import numpy as np
from collections import defaultdict
from itertools import chain
import re
from pathlib import Path
import time
from concurrent.futures import TimeoutError
from pebble import ProcessPool, ProcessExpired
import matplotlib.pyplot as plt
import gSCR
import static_SCR
import dynamic_SCR
import static_NSCR
import dynamic_NSCR


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]                                
MODEL_DATA_DIR = SCRIPT_DIR / "model_data"


def get_keyword_output_paths(keyword: str, analysis: str, mode: str, metric: str):
    keyword_dir = OUTPUT_DIR / f"{analysis}_analysis" / mode / keyword
    return {
        "keyword_dir": keyword_dir,
        "outfile_dir": keyword_dir / "outfiles",
        "figure_dir": keyword_dir / "figures",
        "dyndata_dir": keyword_dir / "raw_out_data",
        "results_file": keyword_dir / f"Strength_Metric_Results_{metric}.xlsx",
        "log_dir": keyword_dir / "logs",
    }

def get_case_bus_data(subsystem):
    bus_nums = psspy.abusint(subsystem, 2, 'NUMBER')[1][0]
    bus_voltage = psspy.abusreal(subsystem, 2, 'BASE')[1][0]
    type_bus = psspy.abusint(subsystem, 2, 'TYPE')[1][0]
    bus_temp = list(map(list, zip(*[bus_nums, bus_voltage, type_bus])))
    bus_df_temp = pd.DataFrame(bus_temp, columns = ["Bus Number", "Base kV", "Bus Code"])
    #get case gen data
    gen_bus = psspy.amachint(subsystem, 4, 'NUMBER')[1][0]
    gen_id = psspy.amachchar(subsystem, 4, 'ID')[1][0]
    gen_mod=psspy.amachint(subsystem, 4, 'WMOD')[1][0]
    gen_status=psspy.amachint(subsystem, 4, 'STATUS')[1][0]
    gen_Pmax = psspy.amachreal(subsystem, 4, 'PMAX')[1][0]
    gen_Pgen = psspy.amachreal(subsystem, 4, 'PGEN')[1][0]
    gen_Mbase = psspy.amachreal(subsystem, 4, 'MBASE')[1][0]
    gen_list = list(map(list, zip(*[gen_bus, gen_id, gen_mod, gen_status, gen_Pmax, gen_Pgen, gen_Mbase])))
    gen_df = pd.DataFrame(gen_list, columns = ["Bus Number", "Gen ID", "WMOD", "Status", "PMAX", "PGEN", "Mbase"])
    gen_df = gen_df.merge(bus_df_temp, on = "Bus Number")
    # REMOVE OUT OF SERVICE BUSES
    gen_df = gen_df[gen_df["Bus Code"] != 4]

    return gen_df

def print_end_time(start_time):
    # Record the ending time
    end_time = time.perf_counter()
    
    # Calculate and display the duration
    elapsed_time = end_time - start_time
    print(f"Total extraction time: {elapsed_time:.6f} seconds")
    return

def main(
    keyword: str,
    analysis: str,
    mode: str,
    metric: str,
    case_file: str | None = None,
    seq_file: str | None = None,
    dyr_file: str | None = None,
):
    global OUTPUT_DIR
    OUTPUT_DIR = PROJECT_ROOT / f"output_{Path(case_file).stem.split('_')[0]}"
    # Record the starting time
    start_time = time.perf_counter()

    #get output paths
    output_paths = get_keyword_output_paths(keyword, analysis, mode, metric)

    # get input case file
    if case_file:
        case = str(Path(case_file).resolve())
        if not os.path.isfile(case):
            sys.exit(f"Specified .sav case file not found: {case}")
    else:
        savcases = glob.glob(str(MODEL_DATA_DIR / "*.sav"))
        if len(savcases) > 1:
            sys.exit("Please only provide one starting network powerflow case (.sav)")
        elif len(savcases) == 0:
            sys.exit("Please provide a starting PSS/E case in the model_data folder")
        case = savcases[0]
    print("starting case : " + case)

    #Start program
    redirect.psse2py()
    psspy.psseinit(800000)

    # suppress output
    #     psspy.report_output(6,'',[])
    psspy.progress_output(6,'',[])
    psspy.alert_output(6,'',[])
    psspy.prompt_output(6,'',[])

    # Open case
    psspy.case(case)

    #get case bus data
    gen_df = get_case_bus_data(-1)
    
    #Calculate initial IBR penetration level (pen_level)
    total_PMaxIBR = gen_df[(gen_df["WMOD"] != 0) & (gen_df["Status"] != 0)]["PMAX"].sum()
    total_case_PMax = gen_df[gen_df["Status"] != 0]["PMAX"].sum()
    pen_level_pct = int(total_PMaxIBR*100/total_case_PMax)
    print("Given network case % IBR penetration: " + str(pen_level_pct))

    ierr = psspy.close_powerflow()
    ierr = psspy.pssehalt_2()
    if ierr !=0:
        sys.exit("psse closed with errors")

    if metric == "SCR":
        if analysis == "static":
            SCR_df = static_SCR.main(1.11, keyword, analysis, mode, case, seq_file)

        elif analysis == "dynamic":
            SCR_df = dynamic_SCR.main(keyword, analysis, mode, case, dyr_file)

    if metric == "NSCR":
        if analysis == "static":
            SCR_df, NSCR_df = static_NSCR.main(1.11, keyword, analysis, mode, case, seq_file)

        elif analysis == "dynamic":
            SCR_df, NSCR_df = dynamic_NSCR.main(keyword, analysis, mode, case, dyr_file)

    if metric == "gSCR":
        pass
    

    print_end_time(start_time)

    return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute system strength metrics.")
    parser.add_argument("--keyword", required=True, choices=["GFL", "GFM", "CONTROL-NEUTRAL"])
    parser.add_argument("--analysis", default="static", choices=["static", "dynamic"])
    parser.add_argument("--mode", default="evolution", choices=["snapshot", "evolution"])
    parser.add_argument("--metric", default="SCR", help="Strength metric type to evaluate (e.g., SCR)")
    parser.add_argument("--case-file", help="Path to a specific PSS/E case (.sav) file.")
    parser.add_argument("--seq-file", help="Path to a specific sequence data (.seq) file for static analysis.")
    parser.add_argument("--dyr-file", help="Path to a specific dynamics (.dyr) file for dynamic analysis.")
    args = parser.parse_args()
    main(
        args.keyword,
        args.analysis,
        args.mode,
        args.metric,
        args.case_file,
        args.seq_file,
        args.dyr_file,
    )