# VRU Urban Traffic Generator

Generate heterogeneous urban traffic scenarios (pedestrians, cyclists,
motorcyclists, and cars) for SUMO and export participant traces for the
NR-SPS (New Radio Sidelink Protocol Simulator).

The project is based on the ETSI TR 138.913 urban micro-cell scenario
(0.25 km² network area).

---

## Features

- **Interactive CLI** – enter a target density (users/km²) and the tool
  proposes a balanced VRU + car distribution.
- **Override control** – refine any count with `-p N -c N -m N -v N`.
- **Automatic SUMO files** – generates `.rou.xml` + `.sumocfg` on the fly.
- **Configurable timing** – warm-up and sampling windows are adjustable
  (defaults: 220 s warm-up + 50 s sampling at 1 ms step resolution).
- **NR-SPS export** – filters persistent participants and writes batch trace
  CSVs ready for the NR-SPS mobility input.

---

## Quick Start

### 1. Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| Python | ≥ 3.10 | |
| [SUMO](https://sumo.dlr.de/) | ≥ 1.18.0 | `sumo` must be on `PATH` |
| numpy | ≥ 1.24 | |
| pandas | ≥ 2.0 | |

Set the SUMO home environment variable before running:

```bash
# Linux / macOS
export SUMO_HOME=/usr/share/sumo

# Windows (PowerShell)
$env:SUMO_HOME = "C:\Program Files (x86)\Eclipse\Sumo"
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Add SUMO network assets

Copy (or symlink) the following files from your Ped_simu_SUMO folder into
`sumo_assets/`:

```
sumo_assets/
├── V3_ETSI_TR_138_913_V14_3_0_urban.net.xml   ← wider sidewalks/crosswalks
└── ETSI_TR_138_913_V14_3_0_urban.poly.xml
```

The V3 network (`V3_ETSI_TR_138_913_V14_3_0_urban.net.xml`) includes widened
sidewalks and crosswalks needed to handle high-density pedestrian scenarios
without SUMO aborting.

### 4. Run

```bash
python main.py
```

---

## Interactive Session Example

```
==============================================================
  VRU Urban Traffic Generator
  ETSI TR 138.913 Urban Scenario  ·  SUMO + NR-SPS
==============================================================

Step 1 – Target Density
──────────────────────────────────────────────────────────────
  Enter target density (users/km²) [e.g. 2000]: 2000

Step 2 – Proposed Distribution
──────────────────────────────────────────────────────────────
  Network area : 0.25 km²
  Total users  : 500   →   2000 users/km²

  Agent                    Count   % of VRU
  ──────────────────────   ───────   ──────────
  Cars (vehicles)            120   —
  Pedestrians                266   70.0%
  Cyclists                    95   25.0%
  Motorcyclists               19    5.0%
  ──────────────────────   ───────   ──────────
  TOTAL                      500

Step 3 – Confirm / Override Distribution
──────────────────────────────────────────────────────────────
  Press ENTER to accept, or enter:  -p N  -c N  -m N  -v N

  > -p 300 -c 60

  ...  (updated table shown, then confirmation prompt)

Step 4 – Simulation Parameters
Step 5 – Generate SUMO Scenario
Step 6 – Run SUMO Simulation
Step 7 – Extract NR-SPS Traces
```

---

## Project Structure

```
VRU_Urban_Traffic_Generator/
├── main.py                # Entry point – interactive CLI
├── config.py              # All constants and defaults
├── scenario_generator.py  # Density math + SUMO XML file generation
├── sumo_runner.py         # TraCI wrapper – runs the simulation
├── trace_extractor.py     # Filters persistent participants → NR-SPS CSV
├── requirements.txt
├── .gitignore
├── sumo_assets/           # Static SUMO network files (not generated)
│   ├── V3_ETSI_TR_138_913_V14_3_0_urban.net.xml
│   └── ETSI_TR_138_913_V14_3_0_urban.poly.xml
└── scenarios/             # Generated per-run (git-ignored output)
    └── p266_c95_m19_v120/
        ├── p266_c95_m19_v120.rou.xml
        ├── p266_c95_m19_v120.sumocfg
        ├── raw_steps/     ← per-step location CSVs (git-ignored)
        └── traces/        ← NR-SPS trace CSVs (git-ignored)
```

---

## Configuration

Edit `config.py` to change persistent defaults:

| Constant | Default | Description |
|---|---|---|
| `SUMO_AREA_KM2` | `0.25` | Network area in km² |
| `MAX_CARS` | `120` | Road capacity cap |
| `STEP_LENGTH` | `0.001` | Simulation step in seconds |
| `DEFAULT_WARMUP_S` | `220` | Warm-up duration (s) |
| `DEFAULT_SAMPLING_S` | `50` | Sampling window (s) |
| `DEFAULT_VRU_SPLIT` | `ped 70% / bike 25% / moto 5%` | Default VRU proportions |

---

## Output Format

### Raw step files (`raw_steps/location_step_N.csv`)

One file per simulation step during the sampling window.  Each row:

```
vehicleId, x, y, type_id, speed_m_s, angle_deg
```

### NR-SPS trace files (`traces/traces_batch_N.csv`)

One file per 10 s batch (10 000 steps).  Only participants present in
**every** step of the batch are retained.  Each row:

```
step_index_in_batch, x, y, type_id, speed_m_s, angle_deg
```

---

## Network Notes

The ETSI TR 138.913 V14.3.0 urban network was modified progressively to
handle increasing pedestrian densities:

- **Original** (`ETSI_TR_138_913_V14_3_0_urban.net.xml`) – standard sidewalks.
- **V2** – widened sidewalks.
- **V3** (`V3_ETSI_TR_138_913_V14_3_0_urban.net.xml`) – further widened
  sidewalks *and* crosswalks; used for all density scenarios V0–V19
  (800–6240 users/km²).

For very high pedestrian counts (> ~1000) always use the V3 network.

---

## License

MIT
