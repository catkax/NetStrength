'''
@date: 17 July 2026
@author: Catherine Kauffman

This code calculates SCR from a static powerflow network case, considering a chosen IBR fault current limit (default 1.11pu)
SCR = SCMVA (of each bus with IBRs disconnected) / Pmax (sum of Pmax of IBRs connected to the bus)
 
input data: 
    1. PSS/E ".raw" files with various penetration of GFL IBRs
    2. ".seq" file to 
    3. General IBR fault current limit in p.u.
    
    
Note:
    1. "WECC240_TI_data_zp.seq" includes data only for existing IBRs.
    2. Other IBR SEQ data are assumed by input (point 3 above).

'''

import glob
import argparse
import os
import sys
import pandas as pd
import numpy as np
import re
from concurrent.futures import TimeoutError
from pebble import ProcessPool, ProcessExpired
from pathlib import Path

# Initialize PSS/E
PSSPY_location = r"C:\Program Files\PTI\PSSE36\36.5\PSSPY314"
PSSE_location = r"C:\Program Files\PTI\PSSE36\36.5\PSSBIN"
sys.path.append(PSSPY_location)
os.environ["PATH"] += ";" + PSSPY_location
os.environ["PATH"] += ";" + PSSE_location

# Re-initialize PSS/E in this process
import psse3605
import psspy
from psspy import _i, _f, _s
import redirect
import numpy as np
from collections import defaultdict

# PSS/E will be initialized in each worker process
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]                                
MODEL_DATA_DIR = SCRIPT_DIR / "model_data"
DEFAULT_CURRENT_LIMIT = 1.11

def get_keyword_output_paths(keyword: str, analysis: str, mode: str):
    keyword_dir = OUTPUT_DIR / f"{analysis}_analysis" / mode / keyword
    return {
        "keyword_dir": keyword_dir,
        "results_file": keyword_dir / f"Strength_Metric_Results_SCR.xlsx",
        "log_dir": keyword_dir / "logs",
    }

# Function to extract data from text
def extract_data_from_text(file_path):
    with open(file_path, "r") as file:
        lines = file.readlines()
    
    data = []
    for line in lines:
        match = re.search(r'\s*(\d+)\s*\[.*\]\s*3PH\s*(\d+\.\d+)\s*(\d+\.\d+)', line)
        if match:
            bus_number = match.group(1)
            mva = match.group(2)
            i_amp = match.group(3)
            data.append([bus_number, float(mva), float(i_amp)])
    
    return data

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

def calculate_SCR_with_replacement_multi(args):
    """
    Calculate SCR for a given raw file.
    Args is a tuple: (results_folder, case, seq_file, current_limit, replace_bus_list)
    """
    results_folder, case, seq_file, current_limit, replace_bus_list = args

    # Re-initialize PSS/E in this process
    redirect.psse2py()
    psspy.psseinit(800000)
    #suppress output from PSSE
    #psspy.report_output(6,'',[])
    psspy.progress_output(6,'',[])
    psspy.alert_output(6,'',[])
    psspy.prompt_output(6,'',[])
    
    psspy.case(case)
    psspy.resq(seq_file)

    gen_df = get_case_bus_data(-1)
    for index, gen in gen_df[(gen_df["WMOD"] == 0) & (gen_df["Bus Number"].isin(replace_bus_list))].iterrows():
        ierr = psspy.machine_chng_4(gen["Bus Number"], gen["Gen ID"], [_i, _i, _i, _i, _i, 1, _i], [_f]*17, "") # change Gen mode from "conventional" to "IBR"
        #print("changing machine : " + str(gen["Gen ID"]) + " at bus: " + str(gen["Bus Number"]) + " to WMOD=1 with error code: " + str(ierr))
    # get the updated mode
    gen_df = get_case_bus_data(-1)

    # apply current limit for all IBRs
    for index, gen in gen_df[gen_df["WMOD"] != 0].iterrows():
        ierr, existing_current_limit = psspy.macdat(gen["Bus Number"],gen["Gen ID"],"IFMAX")
        # sys.exit("existing current limit for bus " + str(gen["Bus Number"]) + " gen " + str(gen["Gen ID"]) + ": " + str(existing_current_limit))
        if existing_current_limit is None:
            psspy.seq_machine_ncs_data(gen["Bus Number"],gen["Gen ID"],1,[current_limit,0.9,1.05],[r"""TICHAR_1""",r"""TICHAR_1"""])
        else:
            print("existing current limit for bus " + str(gen["Bus Number"]) + " gen " + str(gen["Gen ID"]) + ": " + str(existing_current_limit))

    
    #Calculate IBR penetration level (pen_level)
    total_PMaxIBR = gen_df[(gen_df["WMOD"] != 0) & (gen_df["Status"] != 0)]["PMAX"].sum()
    total_case_PMax = gen_df[gen_df["Status"] != 0]["PMAX"].sum()
    pen_level_pct = round(float(total_PMaxIBR*100/total_case_PMax), 4)

    # Initialize a list to store bus numbers with connected generators
    buses_with_generators = sorted(list(set(gen_df["Bus Number"])))
    # sim_fault_buses = sorted(list(set(gen_df[(gen_df["WMOD"] != 0)]["Bus Number"])))
    # non_sim_buses = list(set(buses_with_generators) - set(sim_fault_buses))
    
    # Set up for short circuit calculation
    psspy.short_circuit_units(1) #fault analysis voltage and current output units to physical
    psspy.short_circuit_z_units(1) #fault analysis output impedance units to physical
    psspy.short_circuit_coordinates(1) #voltage and current returned as polar
    psspy.short_circuit_z_coordinates(1) #impedance returned as polar
    #fixed slope decoupled newton raphson
    psspy.fdns([0,0,0,1,1,0,99,0]) #taps disabled, area interchange disabled, phase shift disabled, dc tap adjustment enabled, switched shunts enabled, not flat start, apply var limits on iteration 99, disable non-divergent sol
    
    # evaluate the percentage IBR penetration
    pct_pen_name = str(pen_level_pct)+"_"+(str(replace_bus_list[-1]) if len(replace_bus_list) > 0 else "base")
    ascc_folder = os.path.join(results_folder, "ascc_text_files")
    os.makedirs(ascc_folder, exist_ok = True)
    output_path = os.path.join(ascc_folder, f"scr_calc_{pct_pen_name}.txt")
    
    temp = sys.stdout  
    sys.stdout = open(output_path, "w")
    
    Pmax_sum_each_bus = defaultdict(float)
    for bus in buses_with_generators:
        #filter df for this bus and active IBRs
        gen_df_bus = gen_df[(gen_df["Bus Number"] == bus) & (gen_df["Status"] == 1) & (gen_df["WMOD"] != 0)] 
        # find Pmax sum for active IBRs on this bus
        Pmax = gen_df_bus["PMAX"].sum()
        Pmax_sum_each_bus[bus] = Pmax
        # change status of IBRs with status 1 to 0,  effectively disconnecting all active IBRs on this bus
        for index, gen in gen_df_bus.iterrows():
            psspy.machine_chng_4(gen["Bus Number"], gen["Gen ID"], [0, _i, _i, _i, _i, _i, _i], [_f] * 17, "") 
        # calculate SCMVA of this bus with IBRs disconnected
        psspy.bsys(1,0,[0.0,0.0],0,[],1,bus,0,[],0,[])
        psspy.ascc_3(1,0,[0,0,0,0,0,1,0,0,0,0,1,0,0,0,0,0,0],1.0,"","","")
        #psspy.setdiagresascc_3(2,0,_i,_i,_i,1,0,_i,_i,_i,"") #CK: no need for diagram creation
        # return status of disabled IBRs to 1
        for index, gen in gen_df_bus.iterrows():
            psspy.machine_chng_4(gen["Bus Number"], gen["Gen ID"], [1, _i, _i, _i, _i, _i, _i], [_f] * 17, "")
    sys.stdout.close()
    sys.stdout = temp
     # Extract data
    data = extract_data_from_text(output_path)
    # Create DataFrames
    Pmax_sum_df = pd.DataFrame(list(Pmax_sum_each_bus.items()), columns=["Bus Number", "static_PMaxIBR_"+pct_pen_name])
    SC_df = pd.DataFrame(data, columns=["Bus Number", "static_SCMVA_"+pct_pen_name, "static_SC_AMP_"+pct_pen_name])
    SC_df = SC_df.astype({"Bus Number": "int64"})
    SC_df = SC_df.merge(Pmax_sum_df, how = "outer", on = "Bus Number")
    # for bus in non_sim_buses:
        # SC_df.loc[len(SC_df)] = [bus, 99999, 99999, 0]
    SC_df = SC_df.sort_values(by = "Bus Number").reset_index(drop = True)
    # sys.exit(SC_df)

    SC_df["static_SCR_"+pct_pen_name] = np.where(SC_df["static_PMaxIBR_"+pct_pen_name] == 0, 999, SC_df["static_SCMVA_"+pct_pen_name] / SC_df["static_PMaxIBR_"+pct_pen_name])
    SC_df["static_SCR_"+pct_pen_name] = SC_df["static_SCR_"+pct_pen_name].clip(upper=999)

    return SC_df

def calculate_SCR_with_replacement(args, replace_bus_list):
    """
    Calculate SCR for a given raw file.
    Args is a tuple: case, seq_file, current_limit, replace_bus_list)
    """
    results_folder, case, seq_file, current_limit = args
    # print("converting the following buses to IBR generation: ")
    # print(replace_bus_list)
    
    psspy.case(case)
    psspy.resq(seq_file)

    gen_df = get_case_bus_data(-1)
    for index, gen in gen_df[(gen_df["WMOD"] == 0) & (gen_df["Bus Number"].isin(replace_bus_list))].iterrows():
        # change Gen mode from "conventional" to "IBR"
        ierr = psspy.machine_chng_4(gen["Bus Number"], gen["Gen ID"], [_i, _i, _i, _i, _i, 1, _i], [_f]*17, "") 
        #print("changing machine : " + str(gen["Gen ID"]) + " at bus: " + str(gen["Bus Number"]) + " to WMOD=1 with error code: " + str(ierr))
    # get the updated mode
    gen_df = get_case_bus_data(-1)

    # apply current limit for all IBRs
    for index, gen in gen_df[gen_df["WMOD"] != 0].iterrows():
        ierr, existing_current_limit = psspy.macdat(gen["Bus Number"],gen["Gen ID"],"IFMAX")
        # sys.exit("existing current limit for bus " + str(gen["Bus Number"]) + " gen " + str(gen["Gen ID"]) + ": " + str(existing_current_limit))
        if existing_current_limit is None:
            psspy.seq_machine_ncs_data(gen["Bus Number"],gen["Gen ID"],1,[current_limit,0.9,1.05],[r"""TICHAR_1""",r"""TICHAR_1"""])
        else:
            print("existing current limit for bus " + str(gen["Bus Number"]) + " gen " + str(gen["Gen ID"]) + ": " + str(existing_current_limit)) 
    
    #Calculate IBR penetration level (pen_level)
    total_PMaxIBR = gen_df[(gen_df["WMOD"] != 0) & (gen_df["Status"] != 0)]["PMAX"].sum()
    total_case_PMax = gen_df[gen_df["Status"] != 0]["PMAX"].sum()
    pen_level_pct = round(float(total_PMaxIBR*100/total_case_PMax), 4)
    # sys.exit("PEN LEVEL PCT: " + str(pen_level_pct))

    # Initialize a list to store bus numbers with connected generators
    buses_with_generators = sorted(list(set(gen_df["Bus Number"])))
    # sim_fault_buses = sorted(list(set(gen_df[(gen_df["WMOD"] != 0)]["Bus Number"])))
    # non_sim_buses = list(set(buses_with_generators) - set(sim_fault_buses))
    
    # Set up for short circuit calculation
    psspy.short_circuit_units(1) #fault analysis voltage and current output units to physical
    psspy.short_circuit_z_units(1) #fault analysis output impedance units to physical
    psspy.short_circuit_coordinates(1) #voltage and current returned as polar
    psspy.short_circuit_z_coordinates(1) #impedance returned as polar
    #fixed slope decoupled newton raphson
    psspy.fdns([0,0,0,1,1,0,99,0]) #taps disabled, area interchange disabled, phase shift disabled, dc tap adjustment enabled, switched shunts enabled, not flat start, apply var limits on iteration 99, disable non-divergent sol
    
    # evaluate the percentage IBR penetration
    pct_pen_name = str(pen_level_pct) + "_" + (str(replace_bus_list[-1]) if len(replace_bus_list) > 0 else "base")
    ascc_folder = os.path.join(results_folder, "ascc_text_files")
    os.makedirs(ascc_folder, exist_ok = True)
    output_path = os.path.join(ascc_folder, f"scr_calc_{pct_pen_name}.txt")
    
    temp = sys.stdout  
    sys.stdout = open(output_path, "w")

    Pmax_sum_each_bus = defaultdict(float)
    for bus in buses_with_generators:
        # if bus == 134:
        #     sys.exit("FOUND 134")
        #filter df for this bus and active IBRs
        gen_df_bus = gen_df[(gen_df["Bus Number"] == bus) & (gen_df["Status"] == 1) & (gen_df["WMOD"] != 0)] #Change the WMOD mask if SCR to include contribution from SGs. No zero seq data for machines? Why?
        # find Pmax sum for active IBRs on this bus
        Pmax = gen_df_bus["PMAX"].sum()
        Pmax_sum_each_bus[bus] = Pmax
        # put IBRs out of service on this bus
        for index, gen in gen_df_bus.iterrows():
            psspy.machine_chng_4(gen["Bus Number"], gen["Gen ID"], [0, _i, _i, _i, _i, _i, _i], [_f] * 17, "") 
        # calculate SCMVA of this bus with IBRs disconnected
        psspy.bsys(1,0,[0.0,0.0],0,[],1,bus,0,[],0,[])
        ierr = psspy.ascc_3(1,0,[0,0,0,0,0,1,0,0,0,0,1,0,0,0,0,0,0],1.0,"","","")
        if ierr !=0:
            print("ascc_3 IERR: " + str(ierr))
        # put IBRs back in service
        for index, gen in gen_df_bus.iterrows():
            psspy.machine_chng_4(gen["Bus Number"], gen["Gen ID"], [1, _i, _i, _i, _i, _i, _i], [_f] * 17, "")
    
    sys.stdout.close()
    sys.stdout = temp
    # Extract data
    data = extract_data_from_text(output_path)
    # Create DataFrames
    Pmax_sum_df = pd.DataFrame(list(Pmax_sum_each_bus.items()), columns=["Bus Number", "static_PMaxIBR_"+pct_pen_name])
    SC_df = pd.DataFrame(data, columns=["Bus Number", "static_SCMVA_"+pct_pen_name, "static_SC_AMP_"+pct_pen_name])
    SC_df = SC_df.astype({"Bus Number": "int64"})
    SC_df = SC_df.merge(Pmax_sum_df, how = "outer", on = "Bus Number")
    # for bus in non_sim_buses:
        # SC_df.loc[len(SC_df)] = [bus, 99999, 99999, 0]
    SC_df = SC_df.sort_values(by = "Bus Number").reset_index(drop = True)
    # sys.exit(SC_df)

    SC_df["static_SCR_"+pct_pen_name] = np.where(SC_df["static_PMaxIBR_"+pct_pen_name] == 0, 999, SC_df["static_SCMVA_"+pct_pen_name] / SC_df["static_PMaxIBR_"+pct_pen_name])
    SC_df["static_SCR_"+pct_pen_name] = SC_df["static_SCR_"+pct_pen_name].clip(upper=999)

    next_lowest_SC_df = SC_df.copy()
    lowest_SCR_bus = None
    if len(replace_bus_list) > 0:
        next_lowest_SC_df = next_lowest_SC_df[~(next_lowest_SC_df["Bus Number"].isin(replace_bus_list))]
    if len(next_lowest_SC_df[next_lowest_SC_df["static_SCR_"+pct_pen_name] == next_lowest_SC_df["static_SCR_"+pct_pen_name].min()]) > 0:
        #print(next_lowest_SC_df)
        lowest_SCR_bus = next_lowest_SC_df[next_lowest_SC_df["static_SCR_"+pct_pen_name] == next_lowest_SC_df["static_SCR_"+pct_pen_name].min()]["Bus Number"].iloc[0]
        all_buses_considered = False
    else:
        lowest_SCR_bus = None
        all_buses_considered = True
    #print("found lowest SCR bus: " + str(lowest_SCR_bus))

    return SC_df, lowest_SCR_bus, all_buses_considered

def main(keyword, analysis, mode, case, seq_file, current_limit: float | None = None):
    global OUTPUT_DIR
    OUTPUT_DIR = PROJECT_ROOT / f"output_{"_".join(Path(case).stem.split('_')[:2])}"

    #verify sequence file
    if seq_file:
        seq_file = str(Path(seq_file).resolve())
        if not os.path.isfile(seq_file):
            sys.exit(f"Specified .seq file not found: {seq_file}")
    else:
        seq_files = glob.glob(os.path.join(MODEL_DATA_DIR, "*.seq"))
        if len(seq_files) > 1:
            sys.exit("Multiple .seq files found. Please ensure there is only one .seq file in the directory.")
        if len(seq_files) == 0:
            sys.exit("No .seq file found. Provide one with --seq-file for static analysis.")
        seq_file = seq_files[0]

    #create output folder
    output_paths = get_keyword_output_paths(keyword, analysis, mode)
    results_folder = str(output_paths["keyword_dir"])
    output_paths["keyword_dir"].mkdir(parents=True, exist_ok=True)

    assume_SCR_order_unchanging = True
    
    if current_limit is None:
        current_limit = DEFAULT_CURRENT_LIMIT
    else:
        current_limit = float(current_limit)
        if current_limit <= 0:
            raise ValueError("current_limit must be greater than 0")

    if not case:
        print("No network case file found")
        return
    if not seq_file:
        print("No sequence data file found")
        return

    df_all = None
    result_frames = []
    lowest_SCR_buses = []
    all_buses_considered = False

    #Start program
    redirect.psse2py()
    psspy.psseinit(800000)

    # suppress output
    # psspy.report_output(6,'',[])
    psspy.progress_output(6,'',[])
    psspy.alert_output(6,'',[])
    psspy.prompt_output(6,'',[])
    
    if assume_SCR_order_unchanging and mode == "evolution":
        print("[evolution] Stage 1/3: computing base ordering of weakest SCR buses...")
        args_1 = [results_folder, case, seq_file, current_limit]
        df_temp, lowest_SCR_bus, all_buses_considered = calculate_SCR_with_replacement(args_1, lowest_SCR_buses)
        SCR_col_1 = [k for k in df_temp.columns if "static_SCR" in k][0]
        ordered_df_1 = df_temp.sort_values(by = SCR_col_1)[["Bus Number",SCR_col_1]]
        temp_bus_list = ordered_df_1["Bus Number"].tolist()
        replace_bus_list = [int(x) for x in temp_bus_list]
        args_list = [(results_folder, case, seq_file, current_limit, replace_bus_list[:k]) for k in range(len(replace_bus_list)+1)]
        print(f"[evolution] Stage 2/3: running {len(args_list)} SCR scenarios in parallel...")

        # Use multiprocessing Pool to run calculations in parallel
        # Adjust max_workers based on your CPU cores
        df_temps = []
        with ProcessPool(max_workers=10) as pool:
            future = pool.map(calculate_SCR_with_replacement_multi, args_list, timeout = 60)
            iterator = future.result()
            while True:
                try:
                    result = next(iterator)
                    df_temp = result.copy()
                    df_temps.append(df_temp)
                except StopIteration:
                    break
                except TimeoutError as error:
                    print("function took longer than %d seconds" % error.args[1])
                except ProcessExpired as error:
                    print("%s. Exit code: %d" % (error, error.exitcode))
                except Exception as error:
                    print("function raised %s" % error)
                    print(error.traceback)  # Python's traceback of remote process

        # Merge all results into a single dataframe
        for df_temp in df_temps:
            if df_all is None:
                df_all = df_temp
            else:
                df_all = df_all.merge(df_temp, on="Bus Number", how="outer")
    
    else:
        args = [results_folder, case, seq_file, current_limit]

        if mode == "evolution":
            while not all_buses_considered:
                df_temp, lowest_SCR_bus, all_buses_considered = calculate_SCR_with_replacement(args, lowest_SCR_buses)
                if lowest_SCR_bus is not None:
                    lowest_SCR_buses.append(lowest_SCR_bus)
                if df_all is None:
                    df_all = df_temp
                else:
                    df_all = df_all.merge(df_temp, on="Bus Number", how="outer")
            with pd.ExcelWriter(os.path.join(results_folder,"SGtoIBR_converted_bus_order.xlsx"), engine="xlsxwriter") as writer:
                df_all["Bus Number"].to_excel(writer, index=False)
        else:
            df_temp, lowest_SCR_bus, all_buses_considered = calculate_SCR_with_replacement(args, lowest_SCR_buses)
            df_all = df_temp
    
    # Save to Excel
    # keep_cols = ["Bus Number"] + [col for col in df_all.columns if "static_SCR" in col]
    # df_all = df_all[keep_cols]
    df_all = df_all.round(4)
    results_file = output_paths["results_file"]
    with pd.ExcelWriter(results_file, engine="xlsxwriter") as writer:
        df_all.to_excel(writer, sheet_name=f"{analysis} SCR", index=False)
        worksheet = writer.sheets[f"{analysis} SCR"]
        for idx, col in enumerate(df_all.columns):
            worksheet.set_column(idx, idx, 21)
    print(f"static SCR data successfully saved to {results_file}")
    
    return df_all

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute static SCR metrics.")
    parser.add_argument("--keyword", required=True, choices=["GFL", "GFM", "CONTROL-NEUTRAL"])
    parser.add_argument("--analysis", default="static", choices=["static"])
    parser.add_argument("--mode", default="evolution", choices=["snapshot", "evolution"])
    parser.add_argument("--case-file", required=True, help="Path to a specific PSS/E case (.sav) file.")
    parser.add_argument("--seq-file", required=True, help="Path to a specific sequence data (.seq) file.")
    parser.add_argument("--current-limit", type=float, default=DEFAULT_CURRENT_LIMIT, help="Default IBR current limit in pu.")
    args = parser.parse_args()
    main(
        args.keyword,
        args.analysis,
        args.mode,
        args.case_file,
        args.seq_file,
        current_limit=args.current_limit,
    )

