"""
Calculates the gSCR value for a PSSE system and creates a heatmap of the participation factors towards the gSCR value.
This script was writter by Trager Joswig-Jones (joswitra@uw.edu) and tested using PSS/E 34 and PSS/E 36 
"""
from collections import defaultdict
import numpy as np
import os
import sys
import pandas as pd
from pathlib import Path
import glob
import re

PSSE_LOCATION = r"C:\Program Files\PTI\PSSE36\36.5\PSSBIN"
PSSPY_LOCATION = r"C:\Program Files\PTI\PSSE36\36.5\PSSPY314"
scipy_location = r"C:\Users\ckauffma\AppData\Local\Programs\Python\Python314\Lib\site-packages"
sys.path.append(PSSE_LOCATION)
sys.path.append(PSSPY_LOCATION)
sys.path.append(scipy_location)
os.environ['PATH'] = os.environ['PATH'] + ';' +  PSSPY_LOCATION + ';' +  PSSE_LOCATION + ";" + scipy_location

# Imports
import scipy.linalg as la
try:
    import psse3605
    import psspy  # PSSE API
    import redirect  # For redirecting output
    import sliderPy
except:
    raise ImportError("PSSPY and PSSE paths are not correctly specified. Set sys_path_PSSE and os_path_PSSE in the script.")

# PSSE API constants
SID_ALL = -1
FLAG_INSERVICE = 1
FLAG_ALL_INSERVICE_PLANTS = 2
FLAG_INSERVICE_TYPE14 = 3
FLAG_ALL_MACHINES = 4

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]                                
MODEL_DATA_DIR = SCRIPT_DIR / "model_data"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Configuration
CONFIG = {
    # Model files
    'raw_file': 'WECC240_2018_20RE_PSSE_v2.0.raw',
    'dyr_file': 'WECC240_2018_20RE_PSSE_v2.0.dyr',
    'sld_file': 'one-line.sld',
    # Analysis parameters
    "sys_mbase": 100,
    'top_n_buses': 3,  # Display the n buses with highest participation factors
    'influence': 5,  # range of bus influence
    'bound': 5,  # range of contour beyond buses
    'max_pfactor': None,  # maximum on contour color scale, None for auto set
    'min_pfactor': None,  # minimum on contour color scale, None for zero
    'color': 4,
    'image_file': "gSCR_participation_factor_heatmap",
    # Output files
    'pfact_file': 'pfact.xlsx',
    # Y matrix extraction parameters
    'y_file': 'Y.csv',
    'y_matrix_sid': 1,  # Subsystem ID for Y matrix
    'y_matrix_include_ties': 0,  # Include tie lines (0=no)
    'pinv_rcond': 1e-10,  # Pseudoinverse cutoff used when B_D is singular/ill-conditioned
    'allow_singular_bd_fallback': True,  # Use pinv fallback when direct solve fails
    # Debug
    'debug': False,  # Set to True for verbose output
}

def get_keyword_output_paths(keyword: str, analysis: str, mode: str):
    keyword_dir = OUTPUT_DIR / f"{analysis}_analysis" / mode / keyword
    return {
        "keyword_dir": keyword_dir,
    }

def get_psse_context():
    full_path_executable = sys.executable
    executable = os.path.basename(full_path_executable).lower()
    run_in_psse = False
    case_empty = True
    if 'psse' in executable:
        run_in_psse = True
        ierr, _ = psspy.abuscount()
        if ierr == 1:
            raise ValueError("Working case is empty. Load a case file.")
        case_empty = False
    return run_in_psse, case_empty

def load_cases(files):
    if ".raw" in files["case_file"]:
        psspy.read(0, files["case_file"])
    elif ".sav" in files["case_file"]:
        psspy.case(files["case_file"])
    else:
        sys.exit("case file not found: ", files["case_file"])
    psspy.dyre_new([1, 1, 1, 1], files["dyr_file"])
    file_path = Path(files["case_file"])

    return 

def load_or_use_case(run_in_psse, case_empty):
    sld_file = None
    if run_in_psse and not case_empty:
        print("Using active loaded case file...")
        file_path = os.getcwd()
    else:
        print("Loading case files...")

        raw_file_path = os.path.join(MODEL_DATA_DIR, CONFIG['raw_file'])
        psspy.read(0, raw_file_path)

        dyr_file_path = os.path.join(MODEL_DATA_DIR, CONFIG['dyr_file'])
        psspy.dyre_new([1, 1, 1, 1], dyr_file_path)

        sld_file = CONFIG['sld_file']
    return file_path, sld_file


def compute_gscr_and_participation(files, keyword):
    file_path = Path(files["case_file"]).resolve().parent
    re_match = re.search(r"RE(\d+)", files["case_file"])
    if re_match:
        pen_level = int(re_match.group(1))
    else:
        pen_level = "unknown"
    y_file_path = os.path.join(file_path, CONFIG['y_file'].replace(".csv", "_"+ keyword + "_" + str(pen_level) + ".csv"))
    ierr = psspy.output_y_matrix(CONFIG['y_matrix_sid'], 1, CONFIG['y_matrix_include_ties'], 0, y_file_path)
    if ierr != 0:
        raise RuntimeError("Failed to retrieve the admittance matrix. Error code: " + str(ierr))

    ierr, (bus_numbers, bus_types)  = psspy.abusint(SID_ALL, FLAG_INSERVICE, ['NUMBER', 'TYPE'])
    bus_i_dict = dict(zip(bus_numbers, range(len(bus_numbers))))

    n_bus = psspy.totbus()
    B = np.zeros((n_bus, n_bus), float)
    G = np.zeros((n_bus, n_bus), float)
    Y_df = pd.read_csv(y_file_path)
    Y_df.columns = ["from bus","to bus","G","B"]
    Y_df["from bus i"] = Y_df["from bus"].apply(lambda x: bus_i_dict[x])
    Y_df["to bus i"] = Y_df["to bus"].apply(lambda x: bus_i_dict[x])
    from_idx = Y_df["from bus i"].to_numpy(dtype=int)
    to_idx = Y_df["to bus i"].to_numpy(dtype=int)
    b_vals = Y_df["B"].to_numpy(dtype=float)
    g_vals = Y_df["G"].to_numpy(dtype=float)
    B[from_idx, to_idx] = -b_vals
    G[from_idx, to_idx] = -g_vals
    # bus numbers as labels 
    bus_labels = np.array(bus_numbers, dtype=int)
    b_df = pd.DataFrame(B, index=bus_labels, columns=bus_labels)
    g_df = pd.DataFrame(G, index=bus_labels, columns=bus_labels)

    ierr, n_mach = psspy.amachcount(SID_ALL, FLAG_INSERVICE)
    ierr, (m_bus,) = psspy.amachint(SID_ALL, FLAG_INSERVICE, 'NUMBER')
    ierr, (m_id, m_name) = psspy.amachchar(SID_ALL, FLAG_INSERVICE, ['ID', 'NAME'])

    sg_buses = set()
    GFM_buses = set()
    GFL_buses = set()
    for i in range(n_mach):
        gen_bus = m_bus[i]
        gen_id = m_id[i]
        ierr1, cval = psspy.mdlnam(gen_bus, gen_id, 'GEN')
        ierr2, wcval = psspy.windmnam(gen_bus, gen_id, 'WGEN')
        if ierr1 == 9 or ierr2 == 9:
            raise ValueError("Dynamics data not present in working memory. Load a '.dyr' file.")
        if ierr1 != 0 and ierr2 != 0:
            raise ValueError("Machine model not found. Error codes %s, %s" % (ierr1, ierr2))
        if cval is not None:
            sg_buses.add(gen_bus)
        if wcval is not None:
            if "GFM" in wcval:
                GFM_buses.add(gen_bus)
            else:
                GFL_buses.add(gen_bus)

    GFM_buses_no_sg = GFM_buses - sg_buses
    GFL_buses_no_sg = GFL_buses - sg_buses
    ibr_buses_no_sg = list(GFM_buses_no_sg) + list(GFL_buses_no_sg)
    passive_buses = np.array(list(set(bus_numbers) - set(ibr_buses_no_sg) - sg_buses))

    ierr, (m_bus,) = psspy.amachint(SID_ALL, FLAG_ALL_INSERVICE_PLANTS, 'NUMBER')
    ierr, (m_id, m_name) = psspy.amachchar(SID_ALL, FLAG_ALL_INSERVICE_PLANTS, ['ID', 'NAME'])
    ierr, (m_base, m_mva) = psspy.amachreal(SID_ALL, FLAG_ALL_INSERVICE_PLANTS, ['MBASE', 'MVA'])

    Gen_Sb_dict = defaultdict(float)
    for bus, rating in zip(m_bus, m_base):
        Gen_Sb_dict[bus] += rating

    ibr_mbase = [Gen_Sb_dict[ibr_bus]/CONFIG["sys_mbase"] for ibr_bus in ibr_buses_no_sg]
    Sb = np.diag(ibr_mbase)
    # print(Sb)

    PED_bus_idxs = np.array([bus_i_dict[bus] for bus in ibr_buses_no_sg])
    passive_bus_idxs = np.array([bus_i_dict[bus] for bus in passive_buses])
    inf_bus_idxs = np.array([bus_i_dict[bus] for bus in sg_buses])

    B_A = B[np.ix_(PED_bus_idxs, PED_bus_idxs)]
    B_B = B[np.ix_(PED_bus_idxs, passive_bus_idxs)]
    B_C = B_B.T
    B_D = B[np.ix_(passive_bus_idxs, passive_bus_idxs)]
    # B_E = B[np.ix_(inf_bus_idxs, np.concatenate((PED_bus_idxs, passive_bus_idxs)))].T

    if B_D.size == 0:
        raise ValueError("B_D is empty. Passive bus set is empty, so Kron reduction cannot be formed.")

    bd_rank = np.linalg.matrix_rank(B_D)
    bd_dim = B_D.shape[0]
    bd_cond = np.linalg.cond(B_D)
    if CONFIG['debug']:
        singular_values = np.linalg.svd(B_D, compute_uv=False)
        print(f"B_D shape: {B_D.shape}")
        print(f"B_D rank: {bd_rank}/{bd_dim}")
        print(f"B_D cond: {bd_cond}")
        if singular_values.size > 0:
            print(f"B_D min/max singular values: {singular_values.min()} / {singular_values.max()}")

        # Highlight near-zero rows, which often correspond to disconnected passive buses.
        row_norms = np.linalg.norm(B_D, axis=1)
        weak_idx = np.where(row_norms < 1e-10)[0]
        if weak_idx.size > 0:
            weak_bus_numbers = passive_buses[weak_idx]
            print(f"Near-zero B_D rows at passive bus numbers: {weak_bus_numbers.tolist()}")

    if bd_rank < bd_dim and not CONFIG['allow_singular_bd_fallback']:
        raise np.linalg.LinAlgError(
            f"B_D is rank-deficient ({bd_rank}/{bd_dim}). "
            "Set allow_singular_bd_fallback=True to use pseudoinverse for troubleshooting."
        )

    try:
        # More stable than explicit inverse: solve(B_D, B_C) computes inv(B_D) @ B_C.
        bd_inv_times_bc = np.linalg.solve(B_D, B_C)
    except np.linalg.LinAlgError:
        if not CONFIG['allow_singular_bd_fallback']:
            raise
        print(
            "Warning: B_D is singular or ill-conditioned; "
            f"using pseudoinverse with rcond={CONFIG['pinv_rcond']}"
        )
        bd_inv_times_bc = np.linalg.pinv(B_D, rcond=CONFIG['pinv_rcond']) @ B_C

    B_reduced = B_A - (B_B @ bd_inv_times_bc)
    Yeq = np.matmul(np.linalg.inv(Sb), B_reduced)
    yeq_real_df = pd.DataFrame(np.real(Yeq))
    yeq_imag_df = pd.DataFrame(np.imag(Yeq))
    
    eigenvalues, v_left, v_right = la.eig(Yeq, left=True, right=True)
    gscr = np.min(eigenvalues)

    idx = eigenvalues.argsort()
    eigenvalues = eigenvalues[idx]
    v_right = v_right[:,idx]
    v_left = v_left[:,idx]
    if CONFIG['debug']:
        print("Yeq: ", Yeq)
        print("Yeq Eigenvalues: ", eigenvalues)

    # CK: SHOULD THIS BE CHANGED FROM inversion of right eigenvectors to calculated left eigenvectors?
    v = np.linalg.inv(v_right) # Note this differs from the paper notation as we have W @ lambda @ W^{-1} = Yeq
    # v = np.array(v_left)
    u = np.array(v_right)
    gscr_mode_idx = 0
    participation_factors = (v[gscr_mode_idx, :] * u[:, gscr_mode_idx]).real
    # print("\n".join([str(x) for x in participation_factors]))

    pfact = np.zeros(len(bus_numbers), dtype=float)
    pfact[PED_bus_idxs] = participation_factors
    pfact_df = pd.DataFrame({"Bus Number": bus_numbers,"Participation Factor": pfact})
    pfact_df = pfact_df.sort_values(by = "Participation Factor", ascending = False).reset_index(drop = True)

    output_xlsx = os.path.join(file_path,"gSCR_data_" + keyword + "_" + str(pen_level) + ".xlsx")    
    with pd.ExcelWriter(output_xlsx, engine="openpyxl", mode="w") as writer:
        Y_df.to_excel(writer, sheet_name="Network Admittance", index=False)
        b_df.to_excel(writer, sheet_name="B matrix", index=True)
        g_df.to_excel(writer, sheet_name="G matrix", index=True)
        yeq_real_df.to_excel(writer, sheet_name="Yeq real", index=False)
        yeq_imag_df.to_excel(writer, sheet_name="Yeq imag", index=False)
        pfact_df.to_excel(writer, sheet_name = "PFACT gscr = " + str(np.round(gscr, 3)), index=False)

    return gscr, bus_numbers, pfact_df


def generate_heatmap(file_path, sld_file, bus_numbers, pfact_df):

    slider_loaded = False
    doc = sliderPy.GetActiveDocument()
    diag = doc.GetDiagram()
    if diag.IsValid():
        slider_loaded = True

    if not slider_loaded:
        if sld_file is not None:
            sld_file_path = os.path.join(file_path, sld_file)
            psspy.dyre_new([1, 1, 1, 1], sld_file_path)
            psspy.opendiagfile(sld_file_path)
            slider_loaded = True
        else:
            pass

    if slider_loaded:
        for index, row in pfact_df.items():
            psspy.bus_chng_4(row["Bus Number"], inode=0, realar2 = row["Participation Factor"])

        max_pfactor = pfact_df["Participation Factor"].max() if CONFIG['max_pfactor'] is None else CONFIG['max_pfactor']
        min_pfactor = pfact_df["Participation Factor"].min() if CONFIG['min_pfactor'] is None else CONFIG['min_pfactor']
        psspy.enablediagcontour(element=1, quantity=1, method=1, color=CONFIG['color'], enable=1, res=100, influence=CONFIG['influence'], bound=CONFIG['bound'], max=max_pfactor, min=min_pfactor)

        image_file_path = os.path.join(file_path, CONFIG['image_file'])
        psspy.exportimagefile_3(3, image_file_path, 100)
    else:
        print("Not producing heatmap as a diagram is not the active document.")

def get_gscr_and_pfact(files, keyword):
    #not running in psse gui
    #model files should be loaded here
    psspy.psseinit(800000)
    # suppress output
    psspy.report_output(6,'',[])
    psspy.progress_output(6,'',[])
    psspy.alert_output(6,'',[])
    psspy.prompt_output(6,'',[])

    load_cases(files)
    gscr, bus_numbers, pfact_df = compute_gscr_and_participation(files, keyword)

    psspy.pssehalt_2()

    return gscr, pfact_df

def main():
    psspy.psseinit(80000)

    run_in_psse, case_empty = get_psse_context()
    file_path, sld_file = load_or_use_case(run_in_psse, case_empty)

    gscr, bus_numbers, pfact_df = compute_gscr_and_participation(files)
    print_pfact_df = pfact_df.iloc[:CONFIG["top_n_buses"]].astype(str)
    
    if run_in_psse:
        generate_heatmap(file_path, sld_file, bus_numbers, pfact_df)

    print("gSCR: ", gscr)
    print(
          "Max contributing buses: [", ", ".join(print_pfact_df["Bus Number"]), 
          "] with participation factors: [", ", ".join(print_pfact_df["Participation Factor"]), "]"
          )


if __name__ == '__main__':
    script_dir = Path(__file__).resolve().parent
    savcases = sorted(glob.glob(str(MODEL_DATA_DIR / "*.sav")))
    dyrs = sorted(glob.glob(str(MODEL_DATA_DIR / "*.dyr")))
    print(f"Searching for models in: {MODEL_DATA_DIR}")
    print(f"Found {len(savcases)} .sav and {len(dyrs)} .dyr files")
    case_gscr_pfact = defaultdict(list)

    for i in range(min(len(savcases), len(dyrs))):
        files = {'case_file': savcases[i],
                'dyr_file': dyrs[i],
                'sld_file': None,
                }
        gscr, pfact_df = get_gscr_and_pfact(files)
        print_pfact_df = pfact_df.iloc[:CONFIG["top_n_buses"]].astype(str)

        case_gscr_pfact[files["case_file"]] = [gscr]
    for k, v in case_gscr_pfact.items():
        print(os.path.basename(k))
        print(v)
        print("----------")
    # main()
