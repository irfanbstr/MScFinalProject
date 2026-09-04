import re
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import serial

# --- HARDWARE CONFIGURATION ---
CNC_PORT = "COM6"            # Update to your CNC/GRBL port
SPECTROMETER_PORT = "COM10"  # Update to your Arduino port
BAUD_RATE = 115200

# --- FIXED ABSOLUTE SAMPLE COORDINATES (G53 MCS) ---
START_X = -196.0
START_Y = -122.0

# --- FIXED HOME POSITION ---
HOME_X = -2.0
HOME_Y = -2.0

# --- SCAN CONFIGURATION ---
# GRID_ROWS = 21
# GRID_COLS = 21
# STEP_SIZE = (100.0 / 20.0)     # Moves across the sample grid

GRID_ROWS = 15
GRID_COLS = 15
STEP_SIZE = (100.0 / 14.0)     # Moves across the sample grid


# --- SAFETY HEIGHTS ---
SAFE_Z = -5.0
TOUCH_Z = -15.2

# SPEED CONFIGURATION
FEED_RATE_XY = 500
FEED_RATE_Z = 200

# Channel used for the real-time Matplotlib heatmap
TARGET_CHANNEL = "FY (555nm)"

# All 18 channel names matching Arduino AS7343 output order
ALL_CHANNELS = [
    "FZ (450nm)",  "FY (555nm)",  "FXL (600nm)", "NIR (855nm)", "VIS_1",       "FD_1",
    "F2 (425nm)",  "F3 (475nm)",  "F4 (515nm)",  "F6 (640nm)",  "VIS_2",       "FD_2",
    "F1 (405nm)",  "F7 (690nm)",  "F8 (745nm)",  "F5 (550nm)",  "VIS_3",       "FD_3"
]

# Matrix storage for the live plot
scan_matrix = np.zeros((GRID_ROWS, GRID_COLS), dtype=float)

print("🔌 Opening concurrent hardware links...")
cnc = serial.Serial(CNC_PORT, BAUD_RATE, timeout=2)
instrument = serial.Serial(SPECTROMETER_PORT, BAUD_RATE, timeout=2)
time.sleep(2)
cnc.read_all()
instrument.read_all()


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


def trigger_measurement() -> None:
    """Send the Arduino 'w' command to trigger the reading loop."""
    instrument.write(b"w\n")
    instrument.flush()


def get_full_spectral_measurement() -> dict[str, float]:
    """Read full AS7343 spectral text block and parse all 18 channels into a dict."""
    instrument.reset_input_buffer()
    time.sleep(0.1)

    trigger_measurement()
    time.sleep(0.3)

    raw_lines = []
    start_time = time.time()

    while time.time() - start_time < 3.0:
        if instrument.in_waiting > 0:
            line = instrument.readline().decode("utf-8", errors="ignore").strip()
            if line:
                raw_lines.append(line)
                if "--------------------------------" in line:
                    break
        else:
            time.sleep(0.05)

    # Initialize output dictionary with 0.0 for all 18 channels
    spectral_data = {ch: 0.0 for ch in ALL_CHANNELS}

    for line in raw_lines:
        for ch_name in ALL_CHANNELS:
            if ch_name.lower() in line.lower():
                match = re.search(r":\s*(\d+)", line)
                if match:
                    spectral_data[ch_name] = float(match.group(1))

    return spectral_data


try:
    print("\n🏠 [STEP 1/3] Initiating Automatic System Homing Lifecycle...")
    send_gcode_and_wait("$H")
    print("  -> Homing sequence finished physically.")
    time.sleep(1.0)

    print("\n🔓 [STEP 2/3] Clearing alarm states...")
    send_gcode_and_wait("$X")

    print("\n📐 [STEP 3/3] Setting absolute mode (G90) & mm units (G21)...")
    send_gcode_and_wait("G21")
    send_gcode_and_wait("G90")

    print(f"🛡️ Lifting probe to clearance height: G53 G1 Z{SAFE_Z}")
    send_gcode_and_wait(f"G53 G1 Z{SAFE_Z} F{FEED_RATE_Z}")
    time.sleep(0.2)

    print(f"📍 Moving to absolute start position: G53 G1 X{START_X} Y{START_Y}")
    send_gcode_and_wait(f"G53 G1 X{START_X} Y{START_Y} F{FEED_RATE_XY}")
    time.sleep(0.5)

    output_csv = Path("spectral_scan_full_18ch.csv")
    print(f"\n🚀 Beginning 18-channel spectral scan (Logging live to {output_csv.resolve()})...")

    # Sanitize channel names for CSV headers (remove spaces and parens)
    clean_headers = [ch.replace(" ", "_").replace("(", "").replace(")", "") for ch in ALL_CHANNELS]
    header_str = "Node_ID,Row,Col,X_mm,Y_mm," + ",".join(clean_headers) + "\n"

    with output_csv.open("w", encoding="utf-8") as csv_file:
        csv_file.write(header_str)

        for r in range(GRID_ROWS):
            target_y = START_Y + (r * STEP_SIZE)

            send_gcode_and_wait(f"G53 G1 Z{TOUCH_Z} F{FEED_RATE_Z}")
            send_gcode_and_wait(f"G53 G1 Y{target_y} F{FEED_RATE_XY}")

            for c in range(GRID_COLS):
                target_x = START_X + (c * STEP_SIZE)
                node_idx = (r * GRID_COLS) + c + 1

                print(f"[{node_idx}/{GRID_ROWS * GRID_COLS}] Moving to node (G53 X:{target_x:.1f}, Y:{target_y:.1f})...")
                send_gcode_and_wait(f"G53 G1 X{target_x} Y{target_y} F{FEED_RATE_XY}")
                time.sleep(0.1)

                time.sleep(0.3)

                # Fetch all 18 channels from Arduino
                spectral_dict = get_full_spectral_measurement()
                
                # Store target channel for live visualization
                target_val = spectral_dict.get(TARGET_CHANNEL, 0.0)
                scan_matrix[r, c] = target_val
                print(f"  📊 {TARGET_CHANNEL}: {target_val:.1f}")

                # Format channel values into CSV string
                ch_values_str = ",".join(f"{spectral_dict[ch]:.1f}" for ch in ALL_CHANNELS)
                csv_file.write(f"{node_idx},{r+1},{c+1},{target_x:.2f},{target_y:.2f},{ch_values_str}\n")
                csv_file.flush()  # Stream directly to disk

                time.sleep(0.1)

    print("\n🏁 Scan complete. Returning head to safety position...")
    send_gcode_and_wait(f"G53 G1 Z{SAFE_Z} F{FEED_RATE_Z}")
    send_gcode_and_wait(f"G53 G1 X{HOME_X} Y{HOME_Y} F{FEED_RATE_XY}")

finally:
    cnc.close()
    instrument.close()
    print("🔌 Hardware connections closed safely.")

# --- HEATMAP PLOTTING ---
print("\n📊 Plotting Spectral Reflectance Heatmap...")
plt.figure(figsize=(8, 6.5))

extent_bounds = [
    START_X - (STEP_SIZE / 2),
    START_X + (GRID_COLS - 1) * STEP_SIZE + (STEP_SIZE / 2),
    START_Y - (STEP_SIZE / 2),
    START_Y + (GRID_ROWS - 1) * STEP_SIZE + (STEP_SIZE / 2),
]

im = plt.imshow(
    scan_matrix,
    origin="lower",
    cmap="viridis",
    extent=extent_bounds,
    interpolation="bicubic"
)

cbar = plt.colorbar(im)
cbar.set_label(f"Raw Intensity ({TARGET_CHANNEL})", rotation=270, labelpad=15)

plt.title(f"AS7343 Spatial Reflectance Map ({TARGET_CHANNEL})")
plt.xlabel("X Machine Position (G53 mm)")
plt.ylabel("Y Machine Position (G53 mm)")

# Overlay sampling node points
for r in range(GRID_ROWS):
    for c in range(GRID_COLS):
        x_pos = START_X + (c * STEP_SIZE)
        y_pos = START_Y + (r * STEP_SIZE)
        val = scan_matrix[r, c]
        plt.plot(x_pos, y_pos, "wo", markersize=4, alpha=0.7)
        plt.text(x_pos, y_pos + 1.2, f"{val:.0f}", color="white", fontsize=7, ha="center")

plt.tight_layout()
plt.show()