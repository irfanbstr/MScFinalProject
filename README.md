# Low-Cost Automation of Multi-Property Characterisation Spatial Mapping for Composition Spread Alloy Films (CSAF)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/hardware-CNC3018-red.svg)](https://github.com/grbl/grbl)

This repository contains the codebase, exploratory data analysis, data acquisition scripts, and reference datasets for the MSc dissertation project: **"Low-Cost Automation of Multi-Property Characterisation Spatial Mapping for Composition Spread Alloy Films (CSAF) using Open-Source CNC3018 Platform"** (University of Birmingham).

---

## 📌 Executive Summary

High-throughput characterisation of **Composition Spread Alloy Films (CSAF)** is vital for accelerating Phase Change Materials research, such as **Phase Change Memory (PCM)**. However, commercial automated spatial mapping instruments are financially prohibitive.

This project presents a low-cost, modular, and autonomous multi-property spatial mapping system built on a repurposed 3-axis **CNC3018** platform. Featuring a modular swappable probe architecture, the system performs:
1. **Automated Electrical Characterisation:** Four-Point Probe (4PP) sheet resistance ($R_s$) and bulk resistivity ($\rho$) mapping across dual hardware modes (Low & High Resistivity).
2. **Automated Optical Characterisation:** Spectral reflectance ($R\%$) mapping across 14 visible/NIR bands (405 nm to 855 nm) using an AS7343 multi-spectral sensor.

### Key Results & Benchmarks
* **Validation:** Verified using precision resistors ($10\,\Omega$ to $10\,\mathrm{k}\Omega$), $12\,\mu\mathrm{m}$ Aluminium foil ($\rho = 2.99 \times 10^{-6}\,\Omega\cdot\mathrm{cm}$ vs. baseline $2.65 \times 10^{-6}\,\Omega\cdot\mathrm{cm}$), and 6B graphite deposits.
* **GST Phase-Change Mapping:** Mapped a Germanium-Antimony-Tellurium ($\mathrm{Ge}\text{-}\mathrm{Sb}\text{-}\mathrm{Te}$) CSAF wafer across three thermal states: Amorphous ($25^\circ\mathrm{C}$) and Crystalline ($200^\circ\mathrm{C}$ and $300^\circ\mathrm{C}$).
* **GST-225 Stoichiometry Identification:** Successfully captured bulk resistivity phase switching from $\rho = 331.48\,\Omega\cdot\mathrm{cm}$ (amorphous) down to $\rho = 0.0548\,\Omega\cdot\mathrm{cm}$ ($200^\circ\mathrm{C}$) and $\rho = 0.0154\,\Omega\cdot\mathrm{cm}$ ($300^\circ\mathrm{C}$).

---

## 📁 Repository Structure

```
.
├── 1. Exploratory Data Analysis (Jupyter Notebook)/
│   └── *.ipynb                             # Jupyter notebooks for data analysis, ternary plots, & metrology statistics
│
├── 2. Reflectance Measurement/
│   ├── arduino/                           # Arduino C++ sketch for AS7343 multi-spectral telemetry (I2C)
│   ├── python/                            # Python control scripts & GUI backend for automated optical grid scans
│   ├── dataset/                           # Raw & calibrated reflectance CSV data across thermal states
│   └── references/                        # Related optical literature & reference data
│
├── 3. Resistivity Measurement/
│   ├── arduino/                           # Arduino sketch for ADS1115 16-bit ADC reading & mode switching
│   ├── python/                            # Python GUI, G-code path generator, & resistivity calculation algorithms
│   ├── dataset/                           # Raw 4PP voltage/current measurements & resistivity CSV maps
│   └── references/                        # 4PP geometric correction factors & reference resistivity data
│
├── Irfan Satria_2731349_Final Report.pdf  # Final Submitted Report Document
├── requirements.txt                       # Python dependencies
└── README.md                              # Project documentation
```

---

## 🛠️ System Architecture & Hardware Setup

The physical setup coordinates spatial motion and sensor telemetry using a dual USB serial interface driven by a Flask-based Python web GUI host:

```
                  +-----------------------------------+
                  |           Host PC                 |
                  |     Python Web GUI / Control      |
                  +-----------------+-----------------+
                                    |
          +-------------------------+-------------------------+
          | USB Serial (COM 0)                                | USB Serial (COM 1)
          v                                                   v
+-------------------+                               +-------------------+
|  CNC3018 Board    |                               |   Arduino Nano    |
|   (GRBL v1.1)     |                               |   (Telemetry MCU) |
+---------+---------+                               +---------+---------+
          |                                                   |
          v                                                   v
 3-Axis Stepper Motors                               I2C Bus Protocol
 (X, Y, Z Positioning)                               +--------+--------+
                                                     |                 |
                                                     v                 v
                                            DFRobot ADS1115     SparkFun AS7343
                                              16-bit ADC          Spectrometer
```

### Hardware Circuit Modes:
* **Low Resistivity Mode ($10\,\Omega \text{ to } 1\,\mathrm{k}\Omega/\text{sq}$):** High-current source ($5\,\mathrm{V}, 100\,\mathrm{mA}$) bypassing the picoammeter, reading voltage drops directly via 16-bit ADC.
* **High Resistivity Mode ($>1\,\mathrm{k}\Omega \text{ to } \mathrm{G}\Omega/\text{sq}$):** Low-current sensing ($2\,\mathrm{nA} - 2\,\mathrm{mA}$) integrated with Keithley 485 Picoammeter and MCP6002 Op-Amps ($\sim10\,\mathrm{T}\Omega$ input impedance) to eliminate circuit loading.

---

## 🚀 Getting Started

### Prerequisites

* **Python:** `3.8+`
* **Microcontroller:** Arduino IDE (for building/uploading `.ino` firmware to Arduino Nano)
* **Hardware:** CNC3018 platform (GRBL 1.1 firmware enabled with homing limit switches)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/irfanbstr/MScFinalProject.git
   cd MScFinalProject
   ```

2. **Set up a Python Virtual Environment:**
   ```bash
   python -m venv venv
   # On Linux/macOS:
   source venv/bin/activate
   # On Windows:
   # venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## 💻 Usage & Workflows

### 1. Optical Reflectance Scanning
1. Mount the **SparkFun AS7343 Spectrometer** probe bracket to the 42mm spindle slot.
2. Connect the Arduino Nano and CNC3018 USB cables to the PC.
3. Run the Flask web application in the `2. Reflectance Measurement/python/` directory:
   ```bash
   python app.py
   ```
4. Access the web dashboard at `http://localhost:5000` to homing the CNC machine, calibrate white/dark references, and execute the grid scan.

### 2. Four-Point Probe Resistivity Scanning
1. Mount either the **DIY Pogo-Pin 4PP** (for general samples) or the **Jandel Macor 4PP Probe** (for delicate thin films).
2. Set the DIP switch box to the desired circuit mode (**High-R** or **Low-R**).
3. Run the resistivity mapping app inside `3. Resistivity Measurement/python/`:
   ```bash
   python app.py
   ```
4. Trigger machine homing, configure Z-contact depth, and start the automated 177-point wafer scan routine.

### 3. Exploratory Data Analysis & Ternary Plotting
Open any Jupyter Notebook inside `1. Exploratory Data Analysis (Jupyter Notebook)/` or run directly in Google Colab:
```bash
jupyter notebook
```
> **Colab Interactive Notebook:** [Google Colab Link](https://colab.research.google.com/drive/1kaqdY1cxI8NIREmFfgUynw80iRmRbIqG?usp=sharing)

---

## 📊 Summary of Experimental Results

| Sample / Alloy | State / Temp | Bulk Resistivity $\rho$ | Measured Literature Benchmark | Notes / Status |
| :--- | :--- | :--- | :--- | :--- |
| **Aluminium Foil** ($12\,\mu\mathrm{m}$) | Room Temp ($25^\circ\mathrm{C}$) | $2.99 \times 10^{-6}\,\Omega\cdot\mathrm{cm}$ | $2.65 \times 10^{-6}\,\Omega\cdot\mathrm{cm}$ | 4PP DIY Probe Validation |
| **6B Pencil Graphite** | Light Press | $1.305\,\Omega\cdot\mathrm{cm}$ | $1.157\,\Omega\cdot\mathrm{cm}$ | High-R Mode Validation |
| **GST-225 (Node 120)** | Amorphous ($25^\circ\mathrm{C}$) | $331.48\,\Omega\cdot\mathrm{cm}$ | $280.00\,\Omega\cdot\mathrm{cm}$ | High-Resistivity Phase |
| **GST-225 (Node 120)** | Crystalline ($200^\circ\mathrm{C}$) | $0.0548\,\Omega\cdot\mathrm{cm}$ | $0.0640\,\Omega\cdot\mathrm{cm}$ | Initial Crystallisation Onset |
| **GST-225 (Node 120)** | Crystalline ($300^\circ\mathrm{C}$) | $0.0154\,\Omega\cdot\mathrm{cm}$ | $0.0144\,\Omega\cdot\mathrm{cm}$ | Full Metallic Phase Switch |

---

## 📜 Citation

If you use this project, hardware design, or dataset in your research, please cite:

```bibtex
@mastersthesis{Satria2026CSAF,
  author       = {Irfan Budi Satria},
  title        = {Low-Cost Automation of Multi-Property Characterisation Spatial Mapping for Composition Spread Alloy Films (CSAF) using Open-Source CNC3018 Platform},
  school       = {University of Birmingham},
  department   = {Department of Electronic, Electrical and Systems Engineering},
  year         = {2026},
  type         = {MSc Final Project Report},
  url          = {https://github.com/irfanbstr/MScFinalProject}
}
```

---

## 🤝 Acknowledgments

* **Academic Supervisor:** Dr. Robert Simpson (University of Birmingham)
* **Sponsorship:** Indonesia Endowment Fund for Education Agency (LPDP)
* **Institutional Support:** Department of Electronic, Electrical and Systems Engineering, University of Birmingham.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.