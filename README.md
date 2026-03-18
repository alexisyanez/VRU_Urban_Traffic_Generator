# VRU Urban Traffic Generator

Generate heterogeneous urban traffic scenarios (pedestrians, cyclists,
motorcyclists, and cars) for SUMO and export participant traces for use
in any mobility simulator.

The project is based on the ETSI TR 138.913 urban micro-cell scenario
(0.25 km² network area).

---

## Features

- **Interactive CLI** – enter a target density (users/km²) and the tool
  proposes a balanced VRU + car distribution.
- **Override control** – refine any count with `-p N -c N -m N -v N`.
- **Automatic SUMO files** – generates `.rou.xml` + `.sumocfg` on the fly.
- **Configurable timing** – step size, warm-up and sampling windows are all
  configurable at runtime (defaults: 1 ms steps, 220 s warm-up, 50 s sampling).
- **GUI or headless** – choose between `sumo-gui` and headless `sumo` at run time.
- **Trace export** – filters persistent participants and writes trace CSVs
  ready as mobility input for any simulator.
- **Parallel extraction** – for scenarios with more than 1 000 participants the
  tool detects the load, shows estimated wall-clock times for sequential vs
  parallel extraction, and distributes the work across *N − 1* CPU cores.
  All per-batch results are merged into a single `traces.csv`.
- **Density achievement report** – after extraction, compares the average
  number of persistent participants per batch against the configured target
  and prints a colour-coded pass / warning / fail verdict with actionable advice.

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

Copy (or symlink) the following files into `sumo_assets/`:

```
sumo_assets/
├── V3_ETSI_TR_138_913_V14_3_0_urban.net.xml   ← wider sidewalks/crosswalks
└── ETSI_TR_138_913_V14_3_0_urban.poly.xml
```

The V3 network includes widened sidewalks and crosswalks needed to handle
high-density pedestrian scenarios without SUMO aborting.

### 4. Run

```bash
python main.py
```

---

## Interactive Session Example

```
==============================================================
  VRU Urban Traffic Generator
  ETSI TR 138.913 Urban Scenario  ·  SUMO
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
──────────────────────────────────────────────────────────────
  Simulation timing defaults:
    Step size: 0.001 s
    Warm-up  : 220 s  (220 000 steps)
    Sampling :  50 s  ( 50 000 steps)

  Change timing parameters? [y/N]:

Step 5 – Generate SUMO Scenario
Step 6 – Run SUMO Simulation
──────────────────────────────────────────────────────────────
  (heavy scenario – >1000 participants)

  Mode                              Simulation   Extraction        Total
  ────────────────────────────────  ───────────  ───────────  ──────────
  Sequential  (1 worker)                 8m 12s       22m 05s     30m 17s
  Parallel    (7 workers)                8m 12s        3m 27s     11m 39s

  Use parallel trace extraction (7 workers)? [Y/n]:
  Use SUMO GUI? [y/N]:       ← skipped when parallel mode is selected
  Run SUMO now? [Y/n]:

Step 7 – Extract Traces
──────────────────────────────────────────────────────────────
  Extract trace CSVs now? [Y/n]:
  ...

Density Achievement Report
──────────────────────────────────────────────────────────────
  Expected participants : 500  (2000 users/km²)
  Avg persistent/batch : 487.3  (1949 users/km²)  [best batch: 493]
  ✔  Target density reached  (97.5% of expected participants are persistent).
```

---

## Project Structure

```
VRU_Urban_Traffic_Generator/
├── main.py                # Entry point – interactive CLI
├── config.py              # All constants and defaults
├── scenario_generator.py  # Density math + SUMO XML file generation
├── sumo_runner.py         # TraCI wrapper – runs the simulation
├── trace_extractor.py     # Filters persistent participants → trace CSV(s)
├── requirements.txt
├── .gitignore
├── sumo_assets/           # Static SUMO network files (not generated)
│   ├── V3_ETSI_TR_138_913_V14_3_0_urban.net.xml
│   └── ETSI_TR_138_913_V14_3_0_urban.poly.xml
└── scenarios/             # Generated per-run (git-ignored output)
    └── p266_c95_m19_v120/
        ├── p266_c95_m19_v120.rou.xml
        ├── p266_c95_m19_v120.sumocfg
        ├── raw_steps/          ← per-step location CSVs (git-ignored)
        └── generated_traces/   ← trace CSV(s) (git-ignored)
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

All timing defaults can also be overridden interactively at Step 4 without
editing the file.

---

## Output Format

### Raw step files (`raw_steps/location_step_N.csv`)

One file per simulation step during the sampling window.  Each row:

```
vehicleId, x, y, type_id, speed_m_s, angle_deg
```

### Trace files (`generated_traces/`)

Only participants present in **every** step of a batch are retained, removing
agents that enter or leave mid-batch.  Each row:

```
step_index_in_batch, x, y, type_id, speed_m_s, angle_deg
```

**Sequential mode** – one `traces_batch_N.csv` per 10 s batch (10 000 steps at
1 ms resolution).

**Parallel mode** – all batches are merged into a single `traces.csv` after
parallel processing.

---

## Parallel Extraction

For scenarios with more than **1 000 participants** the tool automatically
detects the heavy load.  It reads the available CPU core count and proposes
using *N − 1* workers (leaving one core free to keep the system responsive).
An estimated time table is printed before asking for confirmation:

- Batch indices are distributed round-robin across workers.
- Each worker writes temporary per-batch files to `generated_traces/_parallel_tmp/`.
- After all workers finish the temp files are concatenated in order and the
  temp folder is deleted.
- **GUI mode is automatically disabled** when parallel extraction is selected,
  since SUMO must run headless for unattended operation.

---

## Density Achievement Report

After extraction the tool compares the average number of persistent
participants per batch against the configured target:

| Result | Threshold | Advice |
|---|---|---|
| ✔ Pass (green) | ≥ 90 % persistent | Target met |
| ⚠ Partial (yellow) | 70 – 89 % | Increase warm-up or reduce sampling window |
| ✖ Fail (red) | < 70 % | Increase warm-up, reduce sampling window, or reduce step size |

---

## Network Notes

The ETSI TR 138.913 V14.3.0 urban network was modified progressively to
handle increasing pedestrian densities:

- **Original** (`ETSI_TR_138_913_V14_3_0_urban.net.xml`) – standard sidewalks.
- **V2** – widened sidewalks.
- **V3** (`V3_ETSI_TR_138_913_V14_3_0_urban.net.xml`) – further widened
  sidewalks *and* crosswalks; recommended for all scenarios.

For very high pedestrian counts (> ~1 000) always use the V3 network.

---

## License

MIT
