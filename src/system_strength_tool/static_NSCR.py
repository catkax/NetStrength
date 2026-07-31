import glob
import os
import sys
import pandas as pd
import numpy as np
import re
from pathlib import Path
import static_SCR

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]                                
MODEL_DATA_DIR = SCRIPT_DIR / "model_data"
DEFAULT_CURRENT_LIMIT = 1.11


def main(current_limit, keyword, analysis, mode, case, seq_file):
    global OUTPUT_DIR
    OUTPUT_DIR = PROJECT_ROOT / f"output_{Path(case).stem.split('_')[0]}"

    # gather static SCR data
    SCR_df = static_SCR.main(current_limit, keyword, analysis, mode, case, seq_file)

    #CHANGE FILE CSV INPUT WHEN DATA IS AVAILABLE
    CSCR_df = pd.read_csv(MODEL_DATA_DIR / "fake_CSCR_input.csv")

    #regularize data types for merge
    CSCR_df['Bus Number'] = CSCR_df['Bus Number'].astype(str)
    SCR_df['Bus Number'] = SCR_df['Bus Number'].astype(str)
    SCR_cols = [col for col in SCR_df.columns if "SCR" in col]
    NSCR_df = pd.DataFrame(SCR_df)
    NSCR_df = pd.merge(NSCR_df, CSCR_df, how = "outer", on = "Bus Number")

    #compute NSCR using input data and SCR results
    for SCR_col in SCR_cols:
        NSCR_df[SCR_col.replace("SCR", "NSCR")] = ((NSCR_df[SCR_col] - NSCR_df["CSCR_min"])/(NSCR_df["CSCR_max"] - NSCR_df["CSCR_min"])).clip(upper=999)

    # write results to excel
    keyword_dir = OUTPUT_DIR / f"{analysis}_analysis" / mode / keyword
    results_file = keyword_dir / f"Strength_Metric_Results_NSCR.xlsx"
    with pd.ExcelWriter(results_file, engine="xlsxwriter") as writer:
        NSCR_df.to_excel(writer, sheet_name=f"{analysis} NSCR", index=False)
        worksheet = writer.sheets[f"{analysis} NSCR"]
        for idx, col in enumerate(NSCR_df.columns):
            worksheet.set_column(idx, idx, 21)
    print(f"{keyword} {analysis} NSCR data successfully saved to {results_file}")
    
    return SCR_df, NSCR_df


    