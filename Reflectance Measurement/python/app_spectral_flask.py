import ast
import csv
import io
import re
import threading
import time
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import serial
from flask import Flask, Response, redirect, render_template, request, send_file, url_for

app = Flask(__name__)
app.config["STATIC_FOLDER"] = str(Path(__file__).parent / "static")

BAUD_RATE = 115200
DEFAULT_CNC_PORT = "COM3"
DEFAULT_SPECTROMETER_PORT = "COM10"
DEFAULT_START_X = -196.0
DEFAULT_START_Y = -122.0
DEFAULT_GRID_ROWS = 15
DEFAULT_GRID_COLS = 15
DEFAULT_STEP_SIZE_TEXT = "100/14"
DEFAULT_SAFE_Z = -5.0
DEFAULT_TOUCH_Z = -15.2
DEFAULT_FEED_RATE_XY = 400
DEFAULT_FEED_RATE_Z = 150

DEFAULT_FORM_VALUES = {
    "cnc_port": DEFAULT_CNC_PORT,
    "spectrometer_port": DEFAULT_SPECTROMETER_PORT,
    "start_x": DEFAULT_START_X,
    "start_y": DEFAULT_START_Y,
    "safe_z": DEFAULT_SAFE_Z,
    "touch_z": DEFAULT_TOUCH_Z,
    "step_size": DEFAULT_STEP_SIZE_TEXT,
    "grid_rows": DEFAULT_GRID_ROWS,
    "grid_cols": DEFAULT_GRID_COLS,
    "feed_rate_xy": DEFAULT_FEED_RATE_XY,
    "feed_rate_z": DEFAULT_FEED_RATE_Z,
    "home_x": -2.0,
    "home_y": -2.0,
}

ALL_CHANNELS = [
    "FZ (450nm)",  "FY (555nm)",  "FXL (600nm)", "NIR (855nm)", "VIS_1",       "FD_1",
    "F2 (425nm)",  "F3 (475nm)",  "F4 (515nm)",  "F6 (640nm)",  "VIS_2",       "FD_2",
    "F1 (405nm)",  "F7 (690nm)",  "F8 (745nm)",  "F5 (550nm)",  "VIS_3",       "FD_3"
]
TARGET_CHANNEL = "FY (555nm)"

state_lock = threading.Lock()
scan_thread: Optional[threading.Thread] = None
abort_event = threading.Event()

scan_state = {
    "running": False,
    "status": "Idle",
    "error": "",
    "matrix": np.zeros((DEFAULT_GRID_ROWS, DEFAULT_GRID_COLS), dtype=float),
    "image_path": None,
    "latest_csv_path": None,
    "console_lines": [],
    "abort_requested": False,
    "form_values": DEFAULT_FORM_VALUES.copy(),
}


def append_log(message: str) -> None:
    with state_lock:
        scan_state["console_lines"].append(message)
        if len(scan_state["console_lines"]) > 300:
            scan_state["console_lines"] = scan_state["console_lines"][-300:]


def update_state(**changes) -> None:
    with state_lock:
        scan_state.update(changes)


def request_abort() -> None:
    global abort_event
    with state_lock:
        scan_state["abort_requested"] = True
        scan_state["status"] = "Abort requested"
    abort_event.set()
    append_log("Abort requested by user")


def get_state_snapshot() -> dict:
    with state_lock:
        return {
            "running": scan_state["running"],
            "status": scan_state["status"],
            "error": scan_state["error"],
            "matrix": scan_state["matrix"].tolist(),
            "image_path": scan_state["image_path"],
            "latest_csv_path": scan_state["latest_csv_path"],
            "console_lines": list(scan_state["console_lines"]),
            "abort_requested": scan_state["abort_requested"],
            "form_values": dict(scan_state["form_values"]),
        }


def serialize_form_values(values: dict) -> str:
    ordered_keys = list(DEFAULT_FORM_VALUES.keys())
    lines = []
    for key in ordered_keys:
        value = values.get(key, DEFAULT_FORM_VALUES[key])
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def load_form_values_from_text(text: str) -> dict:
    loaded = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if key not in DEFAULT_FORM_VALUES:
            continue
        default_value = DEFAULT_FORM_VALUES[key]
        if isinstance(default_value, int):
            loaded[key] = int(value)
        elif isinstance(default_value, float):
            loaded[key] = float(value)
        else:
            loaded[key] = value

    merged = DEFAULT_FORM_VALUES.copy()
    merged.update(loaded)
    return merged


def parse_step_size(raw_value):
    value = str(raw_value).strip()
    if not value:
        return 100.0 / 14.0
    try:
        parsed = float(value)
        return parsed
    except ValueError:
        pass

    try:
        result = eval(value, {"__builtins__": {}}, {})
        return float(result)
    except Exception:
        raise ValueError(f"Invalid step size '{raw_value}'. Use a number or expression like 100/14.")


def save_map_image(matrix: np.ndarray, output_name: str = "spectral_map.png") -> str:
    output_dir = Path(__file__).parent / "static"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / output_name

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(matrix, origin="lower", cmap="viridis")
    fig.colorbar(im, ax=ax, label=f"Raw intensity ({TARGET_CHANNEL})")
    ax.set_title(f"AS7343 Spatial Reflectance Map ({TARGET_CHANNEL})")
    ax.set_xlabel("X Position (mm)")
    ax.set_ylabel("Y Position (mm)")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close(fig)
    return f"static/{output_name}"


def write_csv_file(rows, cols, start_x, start_y, step_size, scan_matrix, measurements, output_name: str = "spectral_scan_full_18ch.csv") -> str:
    output_dir = Path(__file__).parent
    output_path = output_dir / output_name

    clean_headers = [ch.replace(" ", "_").replace("(", "").replace(")", "") for ch in ALL_CHANNELS]
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["Node_ID", "Row", "Col", "X_mm", "Y_mm", *clean_headers])
        for r in range(rows):
            for c in range(cols):
                node_idx = (r * cols) + c + 1
                target_x = float(start_x) + (c * float(step_size))
                target_y = float(start_y) + (r * float(step_size))
                writer.writerow([node_idx, r + 1, c + 1, f"{target_x:.2f}", f"{target_y:.2f}", *measurements[r][c]])

    return str(output_path)


def send_gcode_and_wait(cnc: serial.Serial, cmd: str, sync: bool = True) -> None:
    cnc.write(f"{cmd.strip()}\n".encode("utf-8"))
    while True:
        line = cnc.readline().decode("utf-8", errors="ignore").strip()
        if "ok" in line.lower():
            break
        elif "error" in line.lower():
            raise RuntimeError(f"GRBL error: {line}")
        time.sleep(0.01)

    if sync and any(g in cmd.upper() for g in ["G0", "G1", "G2", "G3", "G53", "$H"]):
        cnc.write(b"G4 P0\n")
        while True:
            line = cnc.readline().decode("utf-8", errors="ignore").strip()
            if "ok" in line.lower():
                break
            if "error" in line.lower():
                raise RuntimeError(f"GRBL error: {line}")
            time.sleep(0.01)


def trigger_measurement(instrument: serial.Serial) -> None:
    instrument.write(b"w\n")
    instrument.flush()
    time.sleep(0.3)


def get_full_spectral_measurement(instrument: serial.Serial) -> dict:
    instrument.reset_input_buffer()
    time.sleep(0.1)

    trigger_measurement(instrument)
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

    spectral_data = {ch: 0.0 for ch in ALL_CHANNELS}
    for line in raw_lines:
        for ch_name in ALL_CHANNELS:
            if ch_name.lower() in line.lower():
                match = re.search(r":\s*(\d+)", line)
                if match:
                    spectral_data[ch_name] = float(match.group(1))
    return spectral_data


def run_scan(params: dict) -> None:
    global scan_thread
    cnc = None
    instrument = None

    abort_event.clear()
    update_state(running=True, status="Opening serial connections", error="", abort_requested=False)

    try:
        if abort_event.is_set():
            raise RuntimeError("Scan aborted by user")

        append_log(f"Opening CNC on {params['cnc_port']} and spectrometer on {params['spectrometer_port']}")
        cnc = serial.Serial(params["cnc_port"], BAUD_RATE, timeout=2)
        instrument = serial.Serial(params["spectrometer_port"], BAUD_RATE, timeout=2)
        time.sleep(2)
        cnc.read_all()
        instrument.read_all()

        append_log("Homing machine")
        update_state(status="Homing machine")
        if abort_event.is_set():
            raise RuntimeError("Scan aborted by user")
        send_gcode_and_wait(cnc, "$H")
        time.sleep(1.0)

        append_log("Clearing alarm state")
        if abort_event.is_set():
            raise RuntimeError("Scan aborted by user")
        send_gcode_and_wait(cnc, "$X")
        append_log("Setting G90 and G21")
        send_gcode_and_wait(cnc, "G21")
        send_gcode_and_wait(cnc, "G90")

        safe_z = float(params["safe_z"])
        touch_z = float(params["touch_z"])
        start_x = float(params["start_x"])
        start_y = float(params["start_y"])
        step_size = float(parse_step_size(params["step_size"]))
        rows = int(params["grid_rows"])
        cols = int(params["grid_cols"])

        if abort_event.is_set():
            raise RuntimeError("Scan aborted by user")
        send_gcode_and_wait(cnc, f"G53 G1 Z{safe_z} F{params['feed_rate_z']}")
        time.sleep(0.2)
        send_gcode_and_wait(cnc, f"G53 G1 X{start_x} Y{start_y} F{params['feed_rate_xy']}")
        time.sleep(0.5)

        scan_matrix = np.zeros((rows, cols), dtype=float)
        measurement_store = [[None for _ in range(cols)] for _ in range(rows)]

        for r in range(rows):
            if abort_event.is_set():
                raise RuntimeError("Scan aborted by user")
            target_y = start_y + (r * step_size)
            send_gcode_and_wait(cnc, f"G53 G1 Z{touch_z} F{params['feed_rate_z']}")
            send_gcode_and_wait(cnc, f"G53 G1 Y{target_y} F{params['feed_rate_xy']}")

            for c in range(cols):
                if abort_event.is_set():
                    raise RuntimeError("Scan aborted by user")
                target_x = start_x + (c * step_size)
                update_state(status=f"Scanning point {r + 1}/{rows}, {c + 1}/{cols}")
                append_log(f"Moving to ({target_x:.2f}, {target_y:.2f})")
                send_gcode_and_wait(cnc, f"G53 G1 X{target_x} Y{target_y} F{params['feed_rate_xy']}")
                time.sleep(0.1)
                # send_gcode_and_wait(cnc, f"G53 G1 Z{touch_z} F{params['feed_rate_z']}")
                # time.sleep(0.3)

                spectral_dict = get_full_spectral_measurement(instrument)
                target_val = spectral_dict.get(TARGET_CHANNEL, 0.0)
                scan_matrix[r, c] = target_val
                measurement_store[r][c] = [f"{spectral_dict[ch]:.1f}" for ch in ALL_CHANNELS]

                append_log(f"  {TARGET_CHANNEL}: {target_val:.1f}")
                update_state(status=f"Logged {TARGET_CHANNEL} = {target_val:.1f} at ({target_x:.2f}, {target_y:.2f})")
                # send_gcode_and_wait(cnc, f"G53 G1 Z{safe_z} F{params['feed_rate_z']}")
                time.sleep(0.1)

        if abort_event.is_set():
            raise RuntimeError("Scan aborted by user")
        send_gcode_and_wait(cnc, f"G53 G1 Z{safe_z} F{params['feed_rate_z']}")
        send_gcode_and_wait(cnc, f"G53 G1 X{params['home_x']} Y{params['home_y']} F{params['feed_rate_xy']}")

        image_path = save_map_image(scan_matrix)
        csv_path = write_csv_file(rows, cols, start_x, start_y, step_size, scan_matrix, measurement_store, "spectral_scan_full_18ch.csv")

        with state_lock:
            scan_state["matrix"] = scan_matrix
            scan_state["image_path"] = image_path
            scan_state["latest_csv_path"] = csv_path
            scan_state["status"] = "Scan complete"
        append_log(f"CSV saved to {csv_path}")
        append_log("Scan complete")

    except Exception as exc:
        if abort_event.is_set():
            append_log("Scan aborted by user")
            update_state(status="Scan aborted", error="")
        else:
            append_log(f"Scan failed: {exc}")
            update_state(status=f"Scan failed: {exc}", error=str(exc))
    finally:
        abort_event.clear()
        with state_lock:
            scan_state["abort_requested"] = False
        if cnc is not None:
            try:
                cnc.close()
            except Exception:
                pass
        if instrument is not None:
            try:
                instrument.close()
            except Exception:
                pass
        update_state(running=False)


@app.route("/", methods=["GET", "POST"])
def index():
    global scan_thread

    if request.method == "POST":
        if scan_state["running"]:
            update_state(status="A scan is already running")
            return redirect(url_for("index"))

        params = {
            "cnc_port": request.form.get("cnc_port", DEFAULT_CNC_PORT),
            "spectrometer_port": request.form.get("spectrometer_port", DEFAULT_SPECTROMETER_PORT),
            "start_x": request.form.get("start_x", DEFAULT_START_X),
            "start_y": request.form.get("start_y", DEFAULT_START_Y),
            "safe_z": request.form.get("safe_z", DEFAULT_SAFE_Z),
            "touch_z": request.form.get("touch_z", DEFAULT_TOUCH_Z),
            "step_size": request.form.get("step_size", DEFAULT_STEP_SIZE_TEXT),
            "grid_rows": request.form.get("grid_rows", DEFAULT_GRID_ROWS),
            "grid_cols": request.form.get("grid_cols", DEFAULT_GRID_COLS),
            "feed_rate_xy": request.form.get("feed_rate_xy", DEFAULT_FEED_RATE_XY),
            "feed_rate_z": request.form.get("feed_rate_z", DEFAULT_FEED_RATE_Z),
            "home_x": request.form.get("home_x", -2.0),
            "home_y": request.form.get("home_y", -2.0),
        }

        try:
            parse_step_size(params["step_size"])
        except ValueError as exc:
            update_state(status="Invalid step size", error=str(exc))
            return redirect(url_for("index"))

        abort_event.clear()
        update_state(abort_requested=False, error="", form_values=params.copy())
        append_log(f"Starting scan with step size {params['step_size']} and grid {params['grid_rows']} x {params['grid_cols']}")
        scan_thread = threading.Thread(target=run_scan, args=(params,), daemon=True)
        scan_thread.start()
        return redirect(url_for("index"))

    return render_template("spectral_ui.html", state=get_state_snapshot())


@app.route("/abort", methods=["POST"])
def abort_scan():
    if scan_state["running"]:
        request_abort()
    else:
        update_state(status="No scan is currently running")
    return redirect(url_for("index"))


@app.route("/save_config")
def save_config():
    config_text = serialize_form_values(scan_state["form_values"])
    return Response(
        config_text,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=spectral_scan_config.txt"},
    )


@app.route("/load_config", methods=["POST"])
def load_config():
    if scan_state["running"]:
        update_state(status="Cannot load config while a scan is running")
        return redirect(url_for("index"))

    uploaded = request.files.get("config_file")
    if uploaded is None or uploaded.filename == "":
        update_state(status="No config file selected", error="")
        return redirect(url_for("index"))

    try:
        text = uploaded.read().decode("utf-8", errors="replace")
        loaded = load_form_values_from_text(text)
        update_state(form_values=loaded, status="Config loaded", error="")
        append_log("Loaded configuration from text file")
    except Exception as exc:
        update_state(status="Failed to load config", error=str(exc))

    return redirect(url_for("index"))


@app.route("/reset_defaults", methods=["POST"])
def reset_defaults():
    if scan_state["running"]:
        update_state(status="Cannot reset settings while a scan is running")
        return redirect(url_for("index"))

    update_state(form_values=DEFAULT_FORM_VALUES.copy(), status="Defaults restored", error="")
    append_log("Restored default scan settings")
    return redirect(url_for("index"))


@app.route("/download_csv")
def download_csv():
    csv_path = scan_state.get("latest_csv_path")
    if not csv_path:
        return Response("No CSV has been generated yet.", mimetype="text/plain")
    return send_file(csv_path, as_attachment=True, download_name=Path(csv_path).name)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
