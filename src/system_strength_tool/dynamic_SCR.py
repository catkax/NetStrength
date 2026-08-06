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

import os, sys
PSSE_LOCATION = r"C:\Program Files\PTI\PSSE36\36.5\PSSBIN"
PSSPY_LOCATION = r"C:\Program Files\PTI\PSSE36\36.5\PSSPY314"
sys.path.append(PSSE_LOCATION)
sys.path.append(PSSPY_LOCATION)
os.environ['PATH'] = os.environ['PATH'] + ';' +  PSSPY_LOCATION + ';' +  PSSE_LOCATION
import psse3605
import psspy
import redirect
import dyntools
from psspy import _i, _f, _s
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


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]                                
MODEL_DATA_DIR = SCRIPT_DIR / "model_data"
REGFMA_icons = [1, 0]
REGFMA_cons = [0.01, 0.01, 0.01, 1.5, 1.15, 0, 0.9, 0, 0.5, -0.5, 0.01, 0.01, 0.01, 0.1, 0.1, 20, 0, 5.86]
REGCA_icons = [1]
REGCA_cons = [0.02,10,0.9,0.4,1.22,1.2,0.9,0.5,-1.3,0.02,0,100,-100,0.7]
EC_model_name = "REECB1"
REECB_icons = [0,0,1,0,0]
# REECB_cons = [0.85,1.15,0.02,-0.05,0.05,5,1,-1,0,0.02,0.5,-0.5,1.1,0.9,2,0.001,1,6,0.05,999,-999,1,0,1.04,0.1]
#Tuning to other WECC Renewable machine electrical models
REECB_cons = [-99,99,0.02,0,0,0,1.1,-1.1,0,0.05,0.44,-0.44,1.05,0.9,0,0.01,10,60,0.02,99,-99,1,0,1.11,0.02]
PC_model_name = "REPCA1"
# REPCA_icons = [0,0,0,0,0,1,1]
# REPCA_cons = [0.02,18,5,0,0.1,-0.8,0,0,0,0.1,-0.1,0,0,1,-1,0.25,0,0.02,-0.0006, 0.0006,10000,-10000,0.8918,-0.8918,0.1,20,20]
#Tuning to other WECC Renewable machine plant models
REPCA_icons = [0,0,0,0,0,0,1]
REPCA_cons = [0.02,18,5,0,0.05,0,0,0,0.02,0.1,-0.1,-1,1,0.43,-0.43,1,0.05,0.25,-1,1,99,-99,1,0,0.1,0,0]


def get_keyword_output_paths(keyword: str, analysis: str, mode: str):
    keyword_dir = OUTPUT_DIR / f"{analysis}_analysis" / mode / keyword
    return {
        "keyword_dir": keyword_dir,
        "outfile_dir": keyword_dir / "outfiles",
        "figure_dir": keyword_dir / "figures",
        "dyndata_dir": keyword_dir / "raw_out_data",
        "results_file": keyword_dir / f"Strength_Metric_Results_SCR.xlsx",
        "log_dir": keyword_dir / "logs",
    }

def get_nlevel_buses(homebus, nlevels):
    """
    Python Syntax:
        lvl_busdict = get_nlevel_buses(savfile, homebus, nlevels)

    Arguments:
        homebus(integer) : Home (starting) bus number to start finding next buses
        nlevels(integer) : Number of levels of buses from Home Bus
    """
    import psspy
    psspy.psseinit()
    
    lvl_list = [n+1 for n in range(nlevels)]

    lvl_busdict = {}
    lvl_busdict[0] = [homebus]

    do_buslist = [homebus]
    done_busdict = {}

    for lvl in lvl_list:
        if not do_buslist: break
        tmp_busdict = {}

        # Search for branches and two winding transformers
        for ibus in do_buslist:
            ierr = psspy.inibrn(ibus, single=2)
            #print("0 inibrn: ierr={}, ibus={}".format(ierr, ibus))
            if ierr == 0:
                while True:
                    ierr,jbus,ickt = psspy.nxtbrn(ibus)
                    #print("1 nxtbrn: ierr={}, jbus={}".format(ierr, jbus))
                    if ierr: break
                    tmp_busdict[jbus] = 1

        # Search for three winding transformers
        for ibus in do_buslist:
            ierr = psspy.inibrn(ibus, single=2)
            if ierr == 0:
                while True:
                    ierr,jbus,kbus,ickt = psspy.nxtbrn3(ibus)
                    #print("2 nxtbrn3: ierr={}, jbus={}, kbus={}".format(ierr, jbus, kbus))
                    if ierr: break
                    tmp_busdict[jbus] = 1
                    if (kbus>0): tmp_busdict[kbus] = 1

        tmp_buslist = list(tmp_busdict.keys())
        tmp_buslist.sort()

        for ibus in do_buslist:
            done_busdict[ibus] = 1

        do_buslist = []
        for ibus in tmp_buslist:
            if ibus not in done_busdict:
                do_buslist.append(ibus)

        lvl_busdict[lvl] = do_buslist[:]

    # all done
    return lvl_busdict

def create_ghost_case(case):
    ghost_cases_dir = OUTPUT_DIR / "ghost_cases"
    ghost_cases_dir.mkdir(parents=True, exist_ok=True)

    #Start program
    redirect.psse2py()
    psspy.psseinit(800000)

    # suppress output
    psspy.report_output(6,'',[])
    psspy.progress_output(6,'',[])
    psspy.alert_output(6,'',[])
    psspy.prompt_output(6,'',[])


    psspy.case(case)
    if "_ghost" not in Path(case).name:
        #Newton Raphson PF solve settings: 99 iterations, tolerance 0.01
        psspy.solution_parameters_5([_i,99,_i,_i,10,_i,_i,20,0],[_f,_f,_f,_f,_f,0.001,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f])
        #ensure evaluation of loading on branches/elements is current expressed as MVA 
        psspy.transformer_percent_units(1)
        psspy.non_trans_percent_units(1)

        #prepare case with ghost buses
        new_case_name = ghost_cases_dir / f"{Path(case).stem}_ghost.sav"
        sub = -1
        _, num = psspy.abusint(sub, 2, ["NUMBER"])
        _, name = psspy.abuschar(sub, 2, ["NAME"])
        _, kV_deg = psspy.abusreal(sub, 2, ["BASE","PU","ANGLED"])
        # bus_kV_deg = np.around(bus_kV_deg,3).tolist()
    
        num.extend(name+kV_deg)
        bus_list = list(map(list, zip(*num)))
        bus_df = pd.DataFrame(bus_list, columns = ["Bus Number", "Bus Name", "Base kV", "Bus Magnitude (pu)", "Bus Angle (deg)"])
        bus_df = bus_df.sort_values(by="Bus Number")
        for index, bus in bus_df.iterrows():
            ghost_num = bus["Bus Number"] + 10000
            ghost_basekV = bus["Base kV"]
            ghost_bustype = 1
            ghost_kVmag = bus["Bus Magnitude (pu)"]
            ghost_angle = bus["Bus Angle (deg)"]
            ghost_name = "GHOST_"+str(index)
            psspy.bus_data_4(ghost_num,0,[ghost_bustype,1,1,1],[ghost_basekV,ghost_kVmag,ghost_angle,_f,_f,_f,_f],ghost_name)
            psspy.branch_data_4(bus["Bus Number"],ghost_num,r"""1""",[1,bus["Bus Number"],1,0,0,0,0],[0.0,0.0002,0.0,0.0,0.0,0.0,0.0,0.0,1.0,1.0,1.0,1.0],[0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0],ghost_name+"b")

        ierr = psspy.save(str(new_case_name))
        if ierr !=0:
            print("saving failed for case : " + str(new_case_name))
        else:
            print("successfully saved : " + str(new_case_name))
    else:
        new_case_name = ghost_cases_dir / f"{Path(case).stem}.sav"
        ierr = psspy.save(str(new_case_name))
        if ierr !=0:
            print("saving failed for case : " + str(new_case_name))
        else:
            print("successfully saved : " + str(new_case_name))

    ierr = psspy.close_powerflow()
    ierr = psspy.pssehalt_2()
    if ierr !=0:
        sys.exit("psse closed with errors")

    print("Done creating ghost cases")
    return new_case_name, ghost_cases_dir

def extract_outfile_dataframe(out_file, figfile_folder, gen_df, pen_level_pct):
    # print("----------------------------------------")
    # print("out file: "+ out_file)
    short_out_file = Path(out_file).stem
    fault_bus = int(short_out_file.split("_")[-1])
    chnfobj = dyntools.CHNF(out_file)
    short_title, chanid, chandata = chnfobj.get_data()
    t = chandata['time']
    chan_categories = {
        'Voltage': [],
        'Angle': [],
        'Active Power': [],
        'Reactive Power': [],
        'Apparent Power (MVA)': [],
        'Terminal Current (pu)': []
    }
    for ch_num, ch_name in chanid.items():
        if ch_num == 'time':
            continue
        #Skip MVA branch flow channels where fault_bus is neither bus
        m = re.search(" "+str(fault_bus), ch_name)
        if m is None:
            continue
        #Skip MVA branch flow channels where fault_bus is the "to" bus
        m = re.search("TO "+str(fault_bus), ch_name)
        if m is not None:
            # print("skipping: " + m.group(0))
            continue
        #do NOT consider machine terminal current for machines not directly connected to the fault bus
        if "ITRM" in ch_name:
            m = re.search("ITRM "+str(fault_bus), ch_name)
            if m is None:
                continue
        #Assign channel category long names
        ch_name_1 = ch_name.upper()
        if "VOLT" in ch_name_1:
            chan_categories['Voltage'].append((ch_num, ch_name))
        elif "ANGL" in ch_name_1:
            chan_categories['Angle'].append((ch_num, ch_name))
        elif "POWR" in ch_name_1:
            chan_categories['Active Power'].append((ch_num, ch_name))
        elif "VARS" in ch_name_1:
            chan_categories['Reactive Power'].append((ch_num, ch_name))
        elif "ITRM" in ch_name_1:
            chan_categories['Terminal Current (pu)'].append((ch_num, ch_name))
        elif "MVA" in ch_name_1:
            chan_categories['Apparent Power (MVA)'].append((ch_num, ch_name))
        else:
            print("cannot find category: "+ ch_name_1)
            sys.exit()

    df = pd.DataFrame()
    df["Time"] = chandata['time']

    for cat_name, channels in chan_categories.items():
        if len(channels) < 1:
            continue
        # print("Category name: " + cat_name + "\n with " + str(len(channels)) + " channels.")
        plt.figure(figsize=(10,6))
        for ch_num, ch_name in channels:
            df[ch_name.strip()] = chandata[ch_num]
            plt.plot(t, chandata[ch_num], label=ch_name, linewidth = 1.0)
        # if "Voltage" in cat_name:
        #     plt.close()
        #     continue
        plt.title(str(pen_level_pct) + "% IBRs Simulation: " + cat_name + " for fault on bus " + str(fault_bus), fontsize=16)
        plt.xlabel('time (s)')
        plt.ylabel(cat_name.split(' '))
        plt.grid(True, linestyle='--', alpha=0.5)
        
        plt.legend(loc = 'upper left', bbox_to_anchor=(1.25, 1.0), fontsize = 8)
        #plt.tight_layout()
        fig_file = short_out_file+"_"+cat_name.replace(" ", "")
        plt.savefig(os.path.join(figfile_folder,fig_file), bbox_inches='tight')
        plt.close()
    
    fault_bus_nomV = gen_df[gen_df["Bus Number"] == fault_bus]["Base kV"].iloc[0]
    for col in df.columns:
        if "MVA" in col:
            from_bus = int(re.search(r"\d+ TO", col).group(0)[:-3])
            from_bus_nomV = gen_df[gen_df["Bus Number"] == from_bus]["Base kV"].iloc[0]
            from_bus_dynV = [col for col in df.columns if str(from_bus) in col and "VOLT" in col][0]
            dynV_volts = from_bus_nomV*df[from_bus_dynV]
            df[col.replace("MVA","IBRCH(kAMPS)")] = round(df[col]/(np.sqrt(3)*dynV_volts), 3)   
        elif "ITRM" in col:
            sys.exit("found machine terminal current in out file")
        else:
            pass
    df["total_I"] = df[list([k for k in df.columns if "kAMPS" in k])].sum(axis=1)
    df["total_MVA"] = df["total_I"] * np.sqrt(3) * fault_bus_nomV
    
    # plot voltage-adjusted final MVA
    plt.figure(figsize=(10,6))
    plt.plot(df["Time"], df["total_MVA"], label="total_MVA", linewidth = 1.0)
    plt.title(str(pen_level_pct) + "% IBRs Simulation: total MVA for fault on bus " + str(fault_bus), fontsize=16)
    plt.xlabel('time (s)')
    plt.ylabel("Apparent Power (MVA)")
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(loc = 'upper left', bbox_to_anchor=(1.25, 1.0), fontsize = 8)
    #plt.tight_layout()
    fig_file = short_out_file+"_AdjustedTotalMVA.png"
    plt.savefig(os.path.join(figfile_folder,fig_file), bbox_inches='tight')
    plt.close()

    return {"pen_level": pen_level_pct, "fault_bus": fault_bus, "out_df": df}

def system_strength_calculation(out_df, pre_fault_time, cycle, PMaxIBR):
    df_postfault = out_df[out_df["Time"].between(pre_fault_time + cycle*1, pre_fault_time + cycle*11)]
    avg_SCMVA = df_postfault["total_MVA"].mean()
    SCR = avg_SCMVA / PMaxIBR if PMaxIBR != 0 else 999
    SCR = SCR if SCR < 999 else 999

    metrics = {
        "dynamic_SCMVA": avg_SCMVA,
        "dynamic_PMaxIBR": PMaxIBR,
        "dynamic_SCR": SCR,
    }

    return metrics, df_postfault

def read_outfile(args):
    out_file, figfile_folder, gen_df, pre_fault_time, cycle, PMax_at_each_bus, pen_level_pct = args
    short_out_file = Path(out_file).stem
    fault_bus = int(short_out_file.split("_")[-1])

    extraction_result = extract_outfile_dataframe(out_file, figfile_folder, gen_df, pen_level_pct)

    PMaxIBR = PMax_at_each_bus[fault_bus]
    strength_metrics, df_postfault = system_strength_calculation(
        extraction_result["out_df"],
        pre_fault_time,
        cycle,
        PMaxIBR,
    )

    return {
        "pen_level": extraction_result["pen_level"],
        "fault_bus": extraction_result["fault_bus"],
        "system_strength_metrics": strength_metrics,
        "out_df": extraction_result["out_df"],
        "processed_df": df_postfault,
    }

def case_conditioning(keyword, pen_level_pct):
    # data = str(pen_level_pct)+"_"+str(keyword)
    # sys.exit(f"GOT HERE TO CASE CONDITIONING: {data}")
    
    # 4005 john day
    john_day_4005 = 1.08
    psspy.plant_chng_4(4035,0,[_i,_i],[john_day_4005,_f])
    psspy.plant_chng_4(4039,0,[_i,_i],[john_day_4005,_f])

    # 4101 COULEE
    coulee_4101 = 1.11
    psspy.plant_chng_4(4131,0,[_i,_i],[coulee_4101,_f])

    #  4202 WCASCADE
    wcascade_4202 = 1.045
    psspy.plant_chng_4(4232,0,[_i,_i],[wcascade_4202,_f])

    # 4201 NORTH
    north_4201 = 1.08
    psspy.plant_chng_4(4231,0,[_i,_i],[north_4201,_f])

    # 4001 MALIN
    malin_4001 = 1.06
    psspy.plant_chng_4(4031,0,[_i,_i],[malin_4001,_f])

    # 4102 HANFORD
    hanford_4102 = 1.08
    psspy.plant_chng_4(4132,0,[_i,_i],[hanford_4102,_f])

    # 6102 MIDPOINT
    midpoint_6102 = 1.115
    psspy.plant_chng_4(6132,0,[_i,_i],[midpoint_6102,_f])

    # 6303 BRIDGER
    bridger_6303 = 1.09
    psspy.plant_chng_4(6333,0,[_i,_i],[bridger_6303,_f])

    # 6403 VALMY
    valmy_6403 = 1.08
    psspy.plant_chng_4(6433,0,[_i,_i],[valmy_6403,_f])

    # 6305 NAUGHTON
    naughton_6305 = 1.04
    psspy.plant_chng_4(6335,0,[_i,_i],[naughton_6305,_f])

    # 3103 SAN MATEO
    sanmateo_3103 = 0.99
    psspy.plant_chng_4(3133,0,[_i,_i],[sanmateo_3103,_f])

    # 3204 PITTSBURG
    pittsburg_3204 = 1.0
    psspy.plant_chng_4(3234,0,[_i,_i],[pittsburg_3204,_f])

    # 2408 MESA CAL
    mesacal_2408 = 1.03
    psspy.plant_chng_4(2438,0,[_i,_i],[mesacal_2408,_f])

    # 2409 MIRALOMA
    miraloma_2409 = 1.03
    psspy.plant_chng_4(2439,0,[_i,_i],[miraloma_2409,_f])

    # 2434 VINCENT
    mesacal_2408 = 1.03
    psspy.plant_chng_4(2438,0,[_i,_i],[mesacal_2408,_f])
    
    gens = [(1034,r"""W"""),(3932, "S"),(2533,r"""S""")] #san juan, s onofre, mossland
    
    for gen in gens:
        
        psspy.change_wnmod_con(gen[0],gen[1],r"""REGFMA1""",13,0.005)
        psspy.change_wnmod_con(gen[0],gen[1],r"""REGFMA1""",7,0.95)


    if "GFM" in keyword:
        
        if int(pen_level_pct) >= 30:
            # 6102 MIDPOINT
            midpoint_6102 = 1.105
            psspy.plant_chng_4(6132,0,[_i,_i],[midpoint_6102,_f])
            # G plant controller tune
            psspy.change_wnmod_con(6132,r"""G""",r"""REGFMA1""",7,0.91)

            # SAN JUAN G4 C and G plant controller tune
            psspy.change_wnmod_con(1034,r"""C""",r"""REGFMA1""",7,0.95)
            psspy.change_wnmod_con(1034,r"""G""",r"""REGFMA1""",7,0.95)

        if int(pen_level_pct) >= 60:
            #adjust naughton exciter model
            psspy.change_plmod_con(6335,r"""H""",r"""SEXS""",6,4.05)
            

        if int(pen_level_pct) >= 70:
            #  4202 WCASCADE
            wcascade_4202 = 1.04
            psspy.plant_chng_4(4232,0,[_i,_i],[wcascade_4202,_f])

            # HANFORD G plant controller tune
            psspy.change_wnmod_con(4132,r"""G""",r"""REGFMA1""",7,0.95)

            # correct PGen from -2 to 0 for NG machine at 3133 san mateo
            psspy.machine_chng_5(3133,r"""NG""",[_i,_i,_i,_i,_i,_i,_i],[0.0,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f],[_s,_s])
        if int(pen_level_pct) >= 80:

            # # 6305 NAUGHTON
            naughton_6305 = 1.0
            psspy.plant_chng_4(6335,0,[_i,_i],[naughton_6305,_f])
            # NAUGHTON C, H plant controller tune
            psspy.change_wnmod_con(6335,r"""C""",r"""REGFMA1""",7,0.95)
            psspy.change_wnmod_con(6335,r"""G""",r"""REGFMA1""",7,0.95)
            psspy.change_wnmod_con(6335,r"""H""",r"""REGFMA1""",7,0.95)

            psspy.change_wnmod_con(6335,r"""H""",r"""REPCA1""",5,50)

            # 8003 COTWDWAP
            cotwdwap_8003 = 1.06
            psspy.plant_chng_4(8033,0,[_i,_i],[cotwdwap_8003,_f])


            # 3701 SUMMIT
            summit_3701 = 0.98
            psspy.plant_chng_4(3731,0,[_i,_i],[summit_3701,_f])
            psspy.change_wnmod_con(3731,r"""NH""",r"""REGFMA1""",7,0.95)


            # 3303 METCALF
            metcalf_3303 = 0.99
            psspy.plant_chng_4(3333,0,[_i,_i],[metcalf_3303,_f])

            # 2612 RINALDI
            rinaldi_2612 = 1.01
            psspy.plant_chng_4(2631,0,[_i,_i],[rinaldi_2612,_f])
            psspy.plant_chng_4(2637,0,[_i,_i],[rinaldi_2612,_f])
            psspy.plant_chng_4(2638,0,[_i,_i],[rinaldi_2612,_f])

            # # 2604 INTERMT
            intermt_2604 = 1.05
            psspy.plant_chng_4(2634,0,[_i,_i],[intermt_2604,_f])
            # INTERMT C plant controller tune
            psspy.change_wnmod_con(2634,r"""C""",r"""REGFMA1""",7,0.95)

            # 6201 COLSTRP 
            psspy.change_wnmod_con(6231,r"""C""",r"""REGFMA1""",7,0.95)

            # 3103 SAN MATEO
            sanmateo_3103 = 0.98
            psspy.plant_chng_4(3133,0,[_i,_i],[sanmateo_3103,_f])

            #3801 DIABLO
            psspy.change_wnmod_con(3831,r"""NN""",r"""REGFMA1""",7,0.95)
            
            # 1301 HOOVER
            psspy.change_wnmod_con(1331,r"""G""",r"""REGFMA1""",7,0.95)
            psspy.change_wnmod_con(1331,r"""H""",r"""REGFMA1""",7,0.95)

    elif "GFL" in keyword:
        if int(pen_level_pct) >= 30:
            # 6102 MIDPOINT
            midpoint_6102 = 1.105
            psspy.plant_chng_4(6132,0,[_i,_i],[midpoint_6102,_f])
        
            #adjust naughton exciter model
            psspy.change_plmod_con(6335,r"""H""",r"""SEXS""",6,4.05)
        
        if int(pen_level_pct) >= 40:
            #  4202 WCASCADE
            wcascade_4202 = 1.04
            psspy.plant_chng_4(4232,0,[_i,_i],[wcascade_4202,_f])


            # correct PGen from -2 to 0 for NG machine at 3133 san mateo
            psspy.machine_chng_5(3133,r"""NG""",[_i,_i,_i,_i,_i,_i,_i],[0.0,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f],[_s,_s])
        
            # # 6305 NAUGHTON
            naughton_6305 = 1.0
            psspy.plant_chng_4(6335,0,[_i,_i],[naughton_6305,_f])

            psspy.change_wnmod_con(6335,r"""H""",r"""REPCA1""",5,50)

            # 8003 COTWDWAP
            cotwdwap_8003 = 1.06
            psspy.plant_chng_4(8033,0,[_i,_i],[cotwdwap_8003,_f])

            # 3701 SUMMIT
            summit_3701 = 0.98
            psspy.plant_chng_4(3731,0,[_i,_i],[summit_3701,_f])

            # 3303 METCALF
            metcalf_3303 = 0.99
            psspy.plant_chng_4(3333,0,[_i,_i],[metcalf_3303,_f])

            # 2612 RINALDI
            rinaldi_2612 = 1.01
            psspy.plant_chng_4(2631,0,[_i,_i],[rinaldi_2612,_f])
            psspy.plant_chng_4(2637,0,[_i,_i],[rinaldi_2612,_f])
            psspy.plant_chng_4(2638,0,[_i,_i],[rinaldi_2612,_f])

            # # 2604 INTERMT
            intermt_2604 = 1.05
            psspy.plant_chng_4(2634,0,[_i,_i],[intermt_2604,_f])

            # 3103 SAN MATEO
            sanmateo_3103 = 0.98
            psspy.plant_chng_4(3133,0,[_i,_i],[sanmateo_3103,_f])
            
    return

def case_dyn_run(args):
    case, dyr_file, outfile_folder, pre_trip_time, pre_fault_time, post_fault_time, fault_bus, keyword, pen_level_pct = args

    redirect.psse2py()
    psspy.psseinit(800000)
    
    # write to log file
    # logfile = os.path.join(log_folder,"check_dyn_converge.log")
    # psspy.report_output(2,logfile,[2,_i])
    # psspy.progress_output(2,logfile,[2,_i])
    # psspy.alert_output(2,logfile,[2,_i])
    # psspy.prompt_output(2,logfile,[2,_i])

    #suppress output
    psspy.report_output(6,'',[])
    psspy.progress_output(6,'',[])
    psspy.alert_output(6,'',[])
    psspy.prompt_output(6,'',[])

    psspy.case(case)
    psspy.dyre_new_2([1,1,1,1],dyr_file)
    #Newton Raphson PF solve settings: 99 iterations, tolerance 0.001
    psspy.solution_parameters_5([_i,99,_i,_i,10,_i,_i,20,0],[_f,_f,_f,_f,_f,0.001,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f])
    #ensure evaluation of loading on branches/elements is current expressed as MVA 
    psspy.transformer_percent_units(1)
    psspy.non_trans_percent_units(1)
    # #ensure timestep is small enough for IBR characteristics
    # psspy.dynamics_solution_param_2([_i,_i,_i,_i,_i,_i,_i,_i],[_f,_f,0.001,_f,_f,_f,_f,_f])

    # change status of IBRs with status 1 to 0, disconnecting all IBRs on the fault bus
    psspy.bsys(3,1,[],0,[],1,[fault_bus],0,[],0,[])
    gen_df = get_case_bus_data(3)
    
    machines_turned_off = []
    PMaxIBR_at_bus = 0
    IBR_PGen_at_bus = 0
    #disconnect IBR gen at the faulted bus
    for index, gen in gen_df[gen_df["WMOD"]!=0].iterrows():
        machines_turned_off.append((gen["Bus Number"], gen["Gen ID"]))
        PMaxIBR_at_bus += gen["PMAX"]
        IBR_PGen_at_bus += gen["PGEN"]
        # psspy.machine_chng_4(gen["Bus Number"], gen["Gen ID"], [0, _i, _i, _i, _i, _i, _i], [_f] * 17, "")

    if "WECC240_2018" in os.path.basename(case):
        case_conditioning(keyword, pen_level_pct)

    #identify bus subsystems of interest
    # lvl_busdict1 = list(get_nlevel_buses(fault_bus, 1).values())
    # fault_buses = list(chain.from_iterable(lvl_busdict1))
    fault_buses = [fault_bus, fault_bus+10000]
    psspy.bsys(2,1,[],0,[],len(fault_buses),fault_buses,0,[],0,[])

    #run PF
    # psspy.fnsl([0,0,0,1,1,1,0,0])
    psspy.fnsl([0,0,0,1,1,0,0,0])
    psspy.fnsl([0,0,0,1,1,0,0,0])
    psspy.fnsl([0,0,0,1,1,0,0,0])
    psspy.fnsl([0,0,0,1,1,0,0,0])
    psspy.fnsl([0,0,0,1,1,0,0,0])

    ## set up output channels
    # psspy.chsb(0,1,[-1,-1,-1,1,1,0])  #ANGLE, machine relative rotor angle (degrees).
    # psspy.chsb(0,1,[-1,-1,-1,1,2,0])  #PELEC, machine electrical power (pu on SBASE).
    # psspy.chsb(0,1,[-1,-1,-1,1,3,0])  #QELEC, machine reactive power.
    # psspy.chsb(0,1,[-1,-1,-1,1,4,0])  #ETERM, machine terminal voltage (pu).
    # psspy.chsb(0,1,[-1,-1,-1,1,6,0])  #PMECH, turbine mechanical power (pu on MBASE).
    # psspy.chsb(0,1,[-1,-1,-1,1,7,0])  #SPEED, machine speed deviation from nominal (pu).
    psspy.chsb(2,0,[-1,-1,-1,1,13,0])  #VOLT, bus pu voltages (complex).
    # psspy.chsb(2,0,[-1,-1,-1,1,16,0])  #flow (P and Q).
    psspy.chsb(2,0,[-1,-1,-1,1,17,0])  #flow (MVA).
    # psspy.chsb(2,0,[-1,-1,-1,1,21,0])  #ITERM.
    # psspy.chsb(0,1,[-1,-1,-1,1,22,0])  #machine apparent impedance.
    # psspy.chsb(0,1,[-1,-1,-1,1,25,0])  #PLOAD.
    # psspy.chsb(0,1,[-1,-1,-1,1,26,0])  #QLOAD.
    # psspy.chsb(0,1,[-1,-1,-1,1,27,0])  #GREF, turbine governor reference.

    # convert generators
    psspy.cong(0)
    # convert loads
    psspy.conl(0,1,1,[0,0],[100.0,0.0,0.0,100.0])
    psspy.conl(0,1,2,[0,0],[100.0,0.0,0.0,100.0])
    psspy.conl(0,1,3,[0,0],[100.0,0.0,0.0,100.0])
    # order and factorize matrix
    psspy.ordr()
    psspy.fact()    
    
    # begin dynamic simulation
    psspy.strt_2([0,0],os.path.join(outfile_folder, str(pen_level_pct)+"_"+str(fault_bus)+".out"))
    ierr = psspy.okstrt()
    if ierr !=0:
        data = str(pen_level_pct)+"_"+str(fault_bus)
        sys.exit(f"INITIAL CONDITIONS SUSPECT: {data}")
    psspy.run(0,pre_trip_time,1,1,0)
    for index, gen in gen_df[(gen_df["WMOD"]!=0) & (gen_df["Status"]!=0)].iterrows():
        if gen["Bus Code"] == 1:
            psspy.bus_chng_4(gen["Bus Number"],0,[2,_i,_i,_i],[_f,_f,_f,_f,_f,_f,_f],_s)
        ierr = psspy.dist_machine_trip(gen["Bus Number"],gen["Gen ID"])
        if ierr !=0:
            print(gen)
            sys.exit("machine trip not executed / executed with error: " + str(ierr))

    psspy.run(0,pre_fault_time,1,1,0)
    ierr = psspy.dist_3phase_bus_fault(fault_bus+10000,0,1,_f,[0.0,-0.2E+10])
    if ierr !=0:
        sys.exit("bus fault not executed / executed with errors")
    psspy.run(0,post_fault_time,1,1,0)
    # psspy.dist_branch_trip(2000,2030,r"""1""")
    # psspy.dist_clear_fault()
    # psspy.run(0,9.0,1,1,0)

    ierr = psspy.close_powerflow()
    ierr = psspy.pssehalt_2()
    if ierr !=0:
        sys.exit("psse closed with errors")
    
    return {"IBRs_disconnected":machines_turned_off, "PMax_at_bus": PMaxIBR_at_bus}

def convert_conv_to_IBR(gen, keyword):
    bus = gen["Bus Number"]
    ID = gen["Gen ID"]

    #remove conventional gen dyn model
    psspy.plmod_remove(bus,ID,1)
    psspy.plmod_remove(bus,ID,7)
    psspy.plmod_remove(bus,ID,3)

    #change machine type to Renewable
    psspy.machine_chng_5(bus,ID,[_i,_i,_i,_i,_i,1,_i],[_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f,_f],[_s,_s])

    #model new renewable dyn models
    if "GFM" in keyword:
        ierr = psspy.add_wind_model(bus,ID,1,"REGFMA1",len(REGFMA_icons),REGFMA_icons,["",""],len(REGFMA_cons),REGFMA_cons)
    else:
        ierr = psspy.add_wind_model(bus,ID,1,"REGCA1",len(REGCA_icons),REGCA_icons,[""],len(REGCA_cons),REGCA_cons)
    if ierr != 0:
        sys.exit("failed to add gen model for : " + str(bus) + " " + ID)
    else:
        print("successfully added gen model for : " + str(bus) + " " + ID)
    if "GFL" in keyword:
        ierr = psspy.add_wind_model(bus,ID,2,EC_model_name,len(REECB_icons),REECB_icons,["","","","",""],len(REECB_cons),REECB_cons)
        if ierr != 0:
            sys.exit("failed to add electrical model for : " + str(bus) + " " + ID)
        else:
            print("successfully added electrical model for : " + str(bus) + " " + ID)
    ierr = psspy.add_wind_model(bus,ID,7,PC_model_name,len(REPCA_icons),REPCA_icons,["","","","","","",""],len(REPCA_cons),REPCA_cons)
    if ierr != 0:
        sys.exit("failed to add plant model for : " + str(bus) + " " + ID)
    else:
        print("successfully added plant model for : " + str(bus) + " " + ID)

    return

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

def main(keyword: str, analysis: str, mode: str, case, dyr_file):
    global OUTPUT_DIR
    OUTPUT_DIR = PROJECT_ROOT / f"output_{"_".join(Path(case).stem.split('_')[:2])}"

    # Record the starting time
    start_time = time.perf_counter()

    #verify dyr file
    if dyr_file:
        dyr_file = str(Path(dyr_file).resolve())
        if not os.path.isfile(dyr_file):
            sys.exit(f"Specified .dyr file not found: {dyr_file}")
    else:
        sys.exit("dyr file not found.")
        
    #make output folder(s)
    output_paths = get_keyword_output_paths(keyword, analysis, mode)
    outfile_folder = str(output_paths["outfile_dir"])
    output_paths["outfile_dir"].mkdir(parents=True, exist_ok=True)
    figfile_folder = str(output_paths["figure_dir"])
    output_paths["figure_dir"].mkdir(parents=True, exist_ok=True)
    # log_folder = str(output_paths["log_dir"])
    # output_paths["log_dir"].mkdir(parents=True, exist_ok=True)

    # Get network powerflow model
    if not case:
        print("No network case file found")
        return
    ghost_case_file, ghost_cases_dir = create_ghost_case(case)
    case = str(ghost_case_file)
    print("starting case : " + case)

    # Check dynamics data input
    if not dyr_file:
        print("No dynamic data file found")
        return
    
    # Define dynamic simulation length, pre and post fault
    pre_trip_time = 0.1
    pre_fault_time = 1
    post_fault_time = 1.5
    cycle = 0.0167

    # Define data structures outside loops
    SGonly_bus_lists = defaultdict(list)
    out_df_dict = defaultdict(pd.DataFrame)
    postfault_df_dict = defaultdict(pd.DataFrame)
    strength_vals = defaultdict(dict)
    gSCR_vals = defaultdict(dict)


    #Start program
    redirect.psse2py()
    psspy.psseinit(800000)

    # suppress output
    psspy.report_output(6,'',[])
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
    print("Starting % IBR penetration: " + str(pen_level_pct))

    if mode == "evolution":
        # Determine IBR penetration levels to evaluate
        max_IBR_pen_level = 100
        num_elements = int(round((max_IBR_pen_level - pen_level_pct) / 10)) + 1
        pen_level_pcts = np.linspace(pen_level_pct, max_IBR_pen_level, num_elements)
        pen_level_pcts = [int(x) for x in pen_level_pcts]
    else:
        pen_level_pcts = [pen_level_pct]

    # Close PSS/E
    ierr = psspy.close_powerflow()
    ierr = psspy.pssehalt_2()
    if ierr !=0:
        sys.exit("psse closed with errors")

    converted_buses = []
    print("-------------------------------------------------")
    for i in range(len(pen_level_pcts)):
        # print("pen level: " + str(pen_level_pct))
        
        # gscr, pfact_df = gSCR.get_gscr_and_pfact({"case_file": case, "dyr_file": dyr_file, "sld_file": None}, keyword)
        # gSCR_vals[os.path.basename(case)] = {"gSCR": gscr, "participation factors": pfact_df}
        # print("----------------------------GSCR calculated----------------------------")

        sub_outfile_folder = os.path.join(outfile_folder,"RE_"+str(pen_level_pct))
        os.makedirs(sub_outfile_folder, exist_ok=True)
        #RUN DYN
        
        #Start program
        redirect.psse2py()
        psspy.psseinit(800000)

        # suppress output
        psspy.report_output(6,'',[])
        psspy.progress_output(6,'',[])
        psspy.alert_output(6,'',[])
        psspy.prompt_output(6,'',[])

        # Open case
        psspy.case(case)

        #get case gen/bus data
        gen_df = get_case_bus_data(-1)

        # Sort unique buses with IBR gen on them, assign to fault_bus list
        full_sim_fault_buses = list(set(gen_df[gen_df["WMOD"] != 0]["Bus Number"]))
        sim_fault_buses = full_sim_fault_buses
        # sim_fault_buses = sim_fault_buses[::10] ##comment out to run all buses
        gen_buses = sorted(list(set(gen_df["Bus Number"])))
        non_sim_buses = list(set(gen_buses) - set(full_sim_fault_buses))
        SGonly_bus_lists[pen_level_pct] = non_sim_buses
        print("Running dynamic simulations for " 
              + str(len(sim_fault_buses)) + " of " + str(len(gen_buses)) + " buses. " 
              + str(len(gen_buses) - len(full_sim_fault_buses))
              + " gen buses do not contain any IBRs and have an assumed SCR of 999.")

        # Close PSS/E
        ierr = psspy.close_powerflow()
        ierr = psspy.pssehalt_2()
        if ierr !=0:
            sys.exit("psse closed with errors")
        
        #prepare arguments for multithreading the dynamic simulations
        args = [(case, dyr_file, sub_outfile_folder, pre_trip_time, pre_fault_time, post_fault_time, fault_bus, keyword, pen_level_pct) for fault_bus in sim_fault_buses]
        PMax_at_each_bus = defaultdict(int)
        sim_start_time = time.perf_counter()

        with ProcessPool(max_workers=10) as pool:
            future = pool.map(case_dyn_run, args, timeout = 60)
            iterator = future.result()

            while True:
                try:
                    result = next(iterator)
                    if len(result["IBRs_disconnected"]) > 0:
                        bus = result["IBRs_disconnected"][0][0]
                        PMax_at_each_bus[bus] = result["PMax_at_bus"]
                except StopIteration:
                    break
                except TimeoutError as error:
                    print("function took longer than %d seconds" % error.args[1])
                except ProcessExpired as error:
                    print("%s. Exit code: %d" % (error, error.exitcode))
                except Exception as error:
                    print("function raised %s" % error)
                    print(error.traceback)  # Python's traceback of remote process
        
        # Calculate and display the duration
        sim_end_time = time.perf_counter()
        print("Dynamic simulations for " + str(len(sim_fault_buses)) + f" bus faults took: {sim_end_time - sim_start_time:.6f} seconds")
        print("skipped simulations for " + str(len(sim_fault_buses)-len(full_sim_fault_buses)) + " gen buses with no IBR")
        
        # extract out files for this pen level
        print("Beginning out file extraction for pen_level: " + keyword + str(pen_level_pct))
        out_files = glob.glob(os.path.join(sub_outfile_folder,"*.out"))
        sub_figfile_folder = os.path.join(figfile_folder,"RE_"+str(pen_level_pct))
        os.makedirs(sub_figfile_folder, exist_ok=True)

        args = [(out_file,sub_figfile_folder, gen_df, pre_fault_time, cycle, PMax_at_each_bus, pen_level_pct) for out_file in out_files]

        with ProcessPool(max_workers=10) as pool:
            future = pool.map(read_outfile, args, timeout = 20)
            iterator = future.result()
            while True:
                        try:
                            result = next(iterator)
                            fault_bus = result["fault_bus"]
                            strength_metrics = result["system_strength_metrics"]
                            metrics = []
                            for metric_name, metric_val in strength_metrics.items():
                                metrics.append(round(metric_val,3))
                            strength_vals[pen_level_pct][fault_bus] = metrics
                            out_df_dict[str(pen_level_pct)+"_"+str(fault_bus)] = result["out_df"]
                            postfault_df_dict[str(pen_level_pct)+"_"+str(fault_bus)] = result["processed_df"]
                        except StopIteration:
                            break
                        except TimeoutError as error:
                            print("function took longer than %d seconds" % error.args[1])
                        except ProcessExpired as error:
                            print("%s. Exit code: %d" % (error, error.exitcode))
                        except Exception as error:
                            print("function raised %s" % error)
                            print(error.traceback)  # Python's traceback of remote process
        
        #add in IBR-less fault bus SCR data
        for bus in non_sim_buses:
            strength_vals[pen_level_pct][bus] = ["N/A","N/A",999]

        flattened_data = [
            (outer_key, inner_key, value[0], value[1], value[2])
            for outer_key, inner_dict in strength_vals.items()
            for inner_key, value in inner_dict.items()
        ]

        SCR_df = pd.DataFrame(flattened_data, columns=['pen_level', 'Bus Number', 'dynamic_SCMVA', "dynamic_PMaxIBR", "dynamic_SCR"])
        print(SCR_df)
        temp_pen_level = pen_level_pct

        print(temp_pen_level)
        psspy.psseinit(800000)

        # suppress output
        psspy.report_output(6,'',[])
        psspy.progress_output(6,'',[])
        psspy.alert_output(6,'',[])
        psspy.prompt_output(6,'',[])
        
        # Open case
        psspy.case(case)
        psspy.dyre_new_2([1,1,1,1],dyr_file)

        while i + 1 < len(pen_level_pcts) and temp_pen_level <= pen_level_pcts[i+1]:

            #find lowest SCR bus that DOES have SG
            temp_df = SCR_df[(SCR_df["pen_level"] == pen_level_pct) & ~(SCR_df["Bus Number"].isin(converted_buses))]
            SG_gen_df = gen_df[(gen_df["WMOD"] == 0) & (gen_df["Status"] != 0)]
            SG_gen_df = SG_gen_df.groupby("Bus Number")["PMAX"].sum()
            temp_df = pd.merge(temp_df, SG_gen_df, how = "outer", on = "Bus Number")
            
            #if all bus strengths are 999, convert smallest PMAX bus
            temp_df = temp_df.sort_values(by=["dynamic_SCR", "PMAX"])
            print(temp_df)
            if len(temp_df) < 1:
                break
            convert_bus = temp_df.iloc[0]["Bus Number"]
            convert_bus_SCR = temp_df.iloc[0]["dynamic_SCR"]

            print("ATTEMPTING TO CONVERT: " + str(convert_bus))
            print("WITH SCR: " + str(convert_bus_SCR))
            converted_buses.append(convert_bus)
            SG_gen_at_bus = gen_df[(gen_df["Bus Number"] == convert_bus) & (gen_df["WMOD"] == 0) & (gen_df["Status"] != 0)]
            # print(SG_gen_at_bus)
            if len(SG_gen_at_bus) < 1:
                print("CONTINUING: NO SG found at: " + str(convert_bus))
                continue
            
            #found bus to convert!
            print("FOUND SGs TO CONVERT AT BUS: " + str(convert_bus))
            
            # convert in sav case and dyr file
            for index, gen in SG_gen_at_bus.iterrows():
                convert_conv_to_IBR(gen, keyword)

            # update pen level variable
            # get updated case gen data
            gen_df = get_case_bus_data(-1)
            # Calculate pen_level
            total_PMaxIBR = gen_df[(gen_df["WMOD"] != 0) & (gen_df["Status"] != 0)]["PMAX"].sum()
            total_case_PMax = gen_df[gen_df["Status"] != 0]["PMAX"].sum()
            temp_pen_level = int(total_PMaxIBR*100/total_case_PMax)
            print("NEW PEN LEVEL: " + str(temp_pen_level))
        
        #save new powerflow case
        if str(pen_level_pct)+".sav" in case:
            case = os.path.join(ghost_cases_dir, os.path.basename(case).replace(str(pen_level_pct)+".sav", str(temp_pen_level)+".sav"))
        else:
            case = os.path.join(ghost_cases_dir, os.path.basename(case).replace(".sav", "_RE"+str(temp_pen_level)+".sav"))
        ierr = psspy.save(case)
        if ierr !=0:
            sys.exit("could not save increased IBR pen case")
        # Save new dynamics data file for increased pen level
        if str(pen_level_pct)+".dyr" in dyr_file:
            dyr_file = os.path.join(ghost_cases_dir, os.path.basename(dyr_file).replace(str(pen_level_pct)+".dyr",str(temp_pen_level)+".dyr"))
        else:
            dyr_file = os.path.join(ghost_cases_dir, os.path.basename(dyr_file).replace(".dyr","_RE"+str(temp_pen_level)+".dyr"))
        ierr = psspy.dyda(0,1,[2,1,0],0,dyr_file)
        if ierr != 0:
            sys.exit("failed to save dynamic data file for : \n" + case + "\n" + dyr_file + "\n" + str(convert_bus))
        # Close PSSE
        ierr = psspy.close_powerflow()
        ierr = psspy.pssehalt_2()
        if ierr !=0:
            sys.exit("psse closed with errors")
        #UPDATE VARIABLE TO CARRY OVER TO NEXT LOOP
        pen_level_pct = temp_pen_level
    
    df_dict = {
            key: pd.DataFrame(
                [(bus, vals[0], vals[1], vals[2]) for bus, vals in d.items()],
                columns=["Bus Number", "dynamic_SCMVA_" + str(key), "dynamic_PMaxIBR_" + str(key), "dynamic_SCR_" + str(key)],
            )
            for key, d in strength_vals.items()
        }   
    dfs = [df for df in df_dict.values()]
    merged_df = dfs[0]
    for df in dfs[1:]:
        merged_df = pd.merge(merged_df, df, on='Bus Number', how='outer')
    merged_df = merged_df.sort_values(by="Bus Number").reset_index(drop=True)
    results_file = output_paths["results_file"]
    with pd.ExcelWriter(results_file, engine='xlsxwriter') as writer:
        merged_df.to_excel(writer, index = False)
        worksheets = writer.sheets
        for sheet in worksheets:
            worksheet = writer.sheets[sheet]
            worksheet.autofit()

    outread_end_time = time.perf_counter()
    print(f"reading outfiles for dynamic simulations took: {outread_end_time - sim_end_time:.6f} seconds")

    # print raw data
    dyndata_folder = str(output_paths["dyndata_dir"])
    output_paths["dyndata_dir"].mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(os.path.join(dyndata_folder, f"dynamic_simulation_results_SCR.xlsx"), engine='xlsxwriter') as writer:     
        for out_file, df in out_df_dict.items():
            df.to_excel(writer, sheet_name= out_file, index = False)
        worksheets = writer.sheets
        for sheet in worksheets:
            worksheet = writer.sheets[sheet]
            worksheet.autofit()
    with pd.ExcelWriter(os.path.join(dyndata_folder, f"postprocessed_dynamic_simulation_results_SCR.xlsx"), engine='xlsxwriter') as writer:     
        for out_file, df in postfault_df_dict.items():
            df.to_excel(writer, sheet_name= out_file, index = False)
        worksheets = writer.sheets
        for sheet in worksheets:
            worksheet = writer.sheets[sheet]
            worksheet.autofit()

    return merged_df

if __name__ == "__main__":
    if "--keyword" not in sys.argv:
        sys.exit("Usage: python extract_metric.py --keyword <GFL|GFM>")
    try:
        keyword = sys.argv[sys.argv.index("--keyword") + 1]
    except IndexError:
        sys.exit("Missing value for --keyword. Usage: python extract_metric.py --keyword <GFL|GFM>")
    main(keyword, "static", "snapshot")