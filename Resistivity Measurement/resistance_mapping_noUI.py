import csv
from pathlib import Path
import re
import time

import matplotlib.pyplot as plt
import numpy as np
import serial

# --- HARDWARE CONFIGURATION ---
CNC_PORT = "COM6"            # GRBL port
PROBE_PORT = "COM10"         # Arduino 4PP port
BAUD_RATE = 115200           

# --- MODE L OR H FOR LOW/HIGH RESISTIVITY MEASUREMENTS ---
MEASURE_MODE = "h"            # 'h' for high resistivity, 'l' for low resistivity

# --- WAFER GEOMETRY & GRID CONFIGURATION (177 SQUARES FULL WAFER) ---
# Row layout from bottom (Row 1) to top (Row 15)
WAFER_ROWS = [5, 9, 11, 13, 13, 15, 15, 15, 15, 15, 13, 13, 11, 9, 5]
MAX_ROW_COUNT = 15
PITCH_MM = 6.0               # 5mm square + 1mm score line

# Centre of the leftmost square on the bottom row (Row 1, Col 1)
START_X_BOTTOM_LEFT = -162.0 
START_Y_BOTTOM_LEFT = -110.0 

# Reference X for the extreme leftmost column of a full 15-square row (-192.0 mm)
BASE_X_MIN = START_X_BOTTOM_LEFT - ((MAX_ROW_COUNT - WAFER_ROWS[0]) / 2.0) * PITCH_MM

# Zigzag rows (alternates L->R and R->L to cut travel time)
SERPENTINE_TRAVERSAL = True

# --- FIXED HOME POSITION (SAFE RETRACT LOCATION) ---
HOME_X = -2.0                
HOME_Y = -2.0                

# --- SAFETY HEIGHTS ---
UPPER_Z = -5.0               # Absolute clearance height (mm)
SAFE_Z = -24.0               # Clearance height between nodes (mm)
TOUCH_Z = -26.8              # Probe touchdown compression height (mm)

# --- SPEED CONFIGURATION ---
FEED_RATE_XY = 500           # Horizontal feed rate (mm/min)
FEED_RATE_Z = 100            # Vertical feed rate for probe contact (mm/min)


def generate_wafer_waypoints():
    """Generate coordinate list for all 177 wafer squares (complete geometry including tabs)."""
    waypoints = []
    node_id = 1

    for r_idx, count in enumerate(WAFER_ROWS):
        row_num = r_idx + 1
        y = START_Y_BOTTOM_LEFT + (r_idx * PITCH_MM)
        offset_squares = (MAX_ROW_COUNT - count) / 2.0
        row_start_x = BASE_X_MIN + (offset_squares * PITCH_MM)

        valid_cols = []
        for c_idx in range(count):
            col_num = c_idx + 1
            x = row_start_x + (c_idx * PITCH_MM)
            valid_cols.append((col_num, x))

        # Reverse every odd row if serpentine traversal is enabled
        if SERPENTINE_TRAVERSAL and (r_idx % 2 == 1):
            valid_cols.reverse()

        for col_num, x in valid_cols:
            waypoints.append({
                "node_id": node_id,
                "row": row_num,
                "col": col_num,
                "x": round(x, 2),
                "y": round(y, 2)
            })
            node_id += 1

    return waypoints


print("🔌 Opening concurrent hardware links...")
cnc = serial.Serial(CNC_PORT, BAUD_RATE, timeout=2)
probe = serial.Serial(PROBE_PORT, BAUD_RATE, timeout=2)
time.sleep(2)
cnc.read_all()
probe.read_all()


def send_gcode_and_wait(cmd: str, sync: bool = True) -> None:
    """Send a G-code command to GRBL and wait for physical motion completion."""
    cnc.write(f"{cmd.strip()}\n".encode("utf-8"))
    wait_for_ok()

    if sync and any(g in cmd.upper() for g in ["G0", "G1", "G2", "G3", "G53", "$H"]):
        cnc.write(b"G4 P0\n")  # Zero-second dwell forces buffer synchronization
        wait_for_ok()


def wait_for_ok() -> None:
    """Read lines from GRBL serial until 'ok' or 'error' is received."""
    while True:
        line = cnc.readline().decode("utf-8", errors="ignore").strip()
        if "ok" in line.lower():
            break
        elif "error" in line.lower():
            print(f"⚠️ GRBL Error: {line}")
            break
        time.sleep(0.005)


def trigger_4pp_measurement(mode: str = MEASURE_MODE) -> None:
    """Send the trigger command ('h' for High Resistivity, 'l' for Low) to the Arduino."""
    probe.write(f"{mode.lower()}\n".encode("utf-8"))
    probe.flush()


def get_4pp_full_telemetry(mode: str = MEASURE_MODE) -> dict:
    """Trigger Arduino and parse raw telemetry directly from serial stream."""
    probe.reset_input_buffer()
    time.sleep(0.05)

    trigger_4pp_measurement(mode)

    raw_lines = []
    start_time = time.time()

    while time.time() - start_time < 3.0:
        if probe.in_waiting > 0:
            line = probe.readline().decode("utf-8", errors="ignore").strip()
            if line:
                raw_lines.append(line)
                if "Sheet_R_Ohms_sq" in line:
                    break
        else:
            time.sleep(0.02)

    telemetry = {
        "film_delta_mv": 0.0,
        "calibrated_a2_mv": 0.0,
        "resistance_ohms": np.nan,
        "sheet_r_ohms_sq": np.nan,
    }

    for line in raw_lines:
        m = re.search(r"Diff_Delta_mV:\s*([\d\.-]+)", line)
        if m: telemetry["film_delta_mv"] = float(m.group(1))

        # Support A2 or A3 current monitor labels
        m = re.search(r"Calibrated_A[23]_mV:\s*([\d\.-]+)", line)
        if m: telemetry["calibrated_a2_mv"] = float(m.group(1))

        m = re.search(r"Resistance_Ohms:\s*([\d\.-]+)", line)
        if m: telemetry["resistance_ohms"] = float(m.group(1))

        m = re.search(r"Sheet_R_Ohms_sq:\s*([\d\.-]+)", line)
        if m: telemetry["sheet_r_ohms_sq"] = float(m.group(1))

    # Mask open-circuit / saturated measurements (eGAIN_ONE range goes up to 4096 mV)
    if telemetry["film_delta_mv"] >= 4090.0:
        telemetry["resistance_ohms"] = np.nan
        telemetry["sheet_r_ohms_sq"] = np.nan

    return telemetry


scan_results = []

try:
    waypoints = generate_wafer_waypoints()
    total_nodes = len(waypoints)

    print("\n[STEP 1/3] Initiating Automatic System Homing Lifecycle...")
    send_gcode_and_wait("$H")
    print("  -> Homing sequence finished physically.")
    time.sleep(1.0)

    print("\n[STEP 2/3] Clearing alarm states...")
    send_gcode_and_wait("$X")

    print("\n[STEP 3/3] Setting absolute mode (G90) & mm units (G21)...")
    send_gcode_and_wait("G21")
    send_gcode_and_wait("G90")

    first_pt = waypoints[0]
    print(f"Moving to initial start position: G53 G1 X{first_pt['x']:.1f} Y{first_pt['y']:.1f}")
    send_gcode_and_wait(f"G53 G1 X{first_pt['x']:.1f} Y{first_pt['y']:.1f} F{FEED_RATE_XY}")
    time.sleep(0.5)

    print(f"Lifting probe to clearance height: G53 G1 Z{UPPER_Z}")
    send_gcode_and_wait(f"G53 G1 Z{UPPER_Z} F{FEED_RATE_Z}")
    time.sleep(0.2)

    output_csv = Path("100mm_wafer_177sq_full_scan.csv")
    print(f"\nBeginning full 177-square wafer scan (Logging to {output_csv.resolve()})...\n")

    with output_csv.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["Node_ID", "Row", "Col", "X_mm", "Y_mm", "Delta_mV", "A2_mV", "R_Ohms", "Rs_Ohm_sq", "Rs_MOhm_sq"])

        for pt in waypoints:
            node_idx = pt["node_id"]
            target_x = pt["x"]
            target_y = pt["y"]
            r_num = pt["row"]
            c_num = pt["col"]

            print(
                f"[{node_idx:03d}/{total_nodes}] Row {r_num:02d}, Col {c_num:02d} -> "
                f"(G53 X:{target_x:6.1f}, Y:{target_y:6.1f})..."
            )
            send_gcode_and_wait(f"G53 G1 X{target_x:.1f} Y{target_y:.1f} F{FEED_RATE_XY}")
            time.sleep(0.05)

            print(" Touchdown to square center...")
            send_gcode_and_wait(f"G53 G1 Z{TOUCH_Z} F{FEED_RATE_Z}")
            send_gcode_and_wait("G4 P2.0")  # Settling for ohmic stabilization and RC filter

            print(" Reading 4PP telemetry from Arduino...")
            telemetry = get_4pp_full_telemetry(mode=MEASURE_MODE)
            
            rs_val = telemetry["sheet_r_ohms_sq"]
            rs_mohm = rs_val / 1e6 if not np.isnan(rs_val) else np.nan
            rs_str = f"{rs_mohm:.2f} MΩ/sq" if not np.isnan(rs_mohm) else "OPEN / SAT"
            print(
                f" A2 (V_corr): {telemetry['calibrated_a2_mv']:.2f} mV | "
                f"ΔV (eGAIN_ONE): {telemetry['film_delta_mv']:.2f} mV | "
                f"Rs: {rs_str}"
            )

            # Store record for plotting
            pt_record = {**pt, **telemetry, "rs_mohm": rs_mohm}
            scan_results.append(pt_record)

            # Write formatted output directly to CSV
            writer.writerow([
                node_idx, r_num, c_num, f"{target_x:.1f}", f"{target_y:.1f}",
                f"{telemetry['film_delta_mv']:.4f}", f"{telemetry['calibrated_a2_mv']:.4f}",
                f"{telemetry['resistance_ohms']:.4f}", f"{telemetry['sheet_r_ohms_sq']:.4f}",
                f"{rs_mohm:.4f}"
            ])
            csv_file.flush()

            print(" Retracting probe to safe clearance...")
            send_gcode_and_wait(f"G53 G1 Z{SAFE_Z} F{FEED_RATE_Z}")
            time.sleep(0.05)

    print("\nFull 177-square wafer scan complete. Returning to home position...")
    send_gcode_and_wait(f"G53 G1 Z{UPPER_Z} F{FEED_RATE_Z}")
    send_gcode_and_wait(f"G53 G1 X{HOME_X} Y{HOME_Y} F{FEED_RATE_XY}")

finally:
    cnc.close()
    probe.close()
    print("Hardware connections closed safely.")

# --- 2D WAFER SPATIAL HEATMAP PLOTTING ---
if scan_results:
    print("\nGenerating Full Wafer Spatial Map directly from Arduino output...")
    plt.figure(figsize=(9, 8))

    xs = [pt["x"] for pt in scan_results]
    ys = [pt["y"] for pt in scan_results]
    rs_mohm = [pt["rs_mohm"] for pt in scan_results]

    scatter = plt.scatter(
        xs, 
        ys, 
        c=rs_mohm, 
        cmap="viridis", 
        s=160, 
        marker="s", 
        edgecolors="black", 
        linewidths=0.5
    )

    cbar = plt.colorbar(scatter)
    cbar.set_label("Sheet Resistance (M$\\Omega$/sq)", rotation=270, labelpad=15)

    plt.title("100mm Wafer Full Spatial Map (177 Squares)")
    plt.xlabel("X Machine Position (G53 mm)")
    plt.ylabel("Y Machine Position (G53 mm)")
    plt.axis("equal")
    plt.grid(True, linestyle="--", alpha=0.4)

    plt.tight_layout()
    plt.savefig("100mm_wafer_full_spatial_map.png", dpi=300)
    plt.show()