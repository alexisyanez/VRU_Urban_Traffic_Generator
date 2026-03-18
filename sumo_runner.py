"""
sumo_runner.py
~~~~~~~~~~~~~~
Runs a SUMO simulation via TraCI and writes per-timestep location CSV files
during the sampling window.

Output file format (one CSV per simulation step, stored in raw_steps/):
    vehicleId, x, y, type_id, speed, angle

This is a refactored, parametric version of the original two_way_traci.py.
"""

import csv
import os
import sys
from pathlib import Path

# SUMO_HOME must be set in the environment so that the traci package is found.
if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
else:
    raise EnvironmentError(
        "Environment variable 'SUMO_HOME' is not set.\n"
        "Please set it to your SUMO installation directory, e.g.:\n"
        "  Windows:  setx SUMO_HOME 'C:\\Program Files (x86)\\Eclipse\\Sumo'\n"
        "  Linux:    export SUMO_HOME=/usr/share/sumo"
    )

try:
    import traci
except ImportError as exc:
    raise ImportError(
        "Could not import traci.  Make sure SUMO is installed and SUMO_HOME is set."
    ) from exc

import config


def run_simulation(
    sumocfg_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    warmup_steps: int   = config.DEFAULT_WARMUP_STEPS,
    sampling_steps: int = config.DEFAULT_SAMPLING_STEPS,
    step_length: float  = config.STEP_LENGTH,
    use_gui: bool       = False,
    verbose: bool       = True,
) -> Path:
    """Run SUMO via TraCI and record participant positions during the sampling window.

    Parameters
    ----------
    sumocfg_path   : Path to the .sumocfg file for this scenario.
    output_dir     : Directory where raw per-step CSV files will be written.
                     A sub-folder ``raw_steps/`` is created automatically.
    warmup_steps   : Number of steps to run before data collection starts.
    sampling_steps : Number of steps to record after the warm-up.
    step_length    : Simulation step size in seconds (used for progress display).
    use_gui        : Launch ``sumo-gui`` instead of headless ``sumo``.
    verbose        : Print progress every 10 000 steps when True.

    Returns
    -------
    Path to the ``raw_steps/`` directory containing the per-step CSVs.
    """
    sumocfg_path = Path(sumocfg_path).resolve()
    raw_steps_dir = Path(output_dir) / "raw_steps"
    raw_steps_dir.mkdir(parents=True, exist_ok=True)

    total_steps = warmup_steps + sampling_steps
    sumo_binary = "sumo-gui" if use_gui else "sumo"
    sumo_cmd = [sumo_binary, "-c", str(sumocfg_path)]

    if verbose:
        print(f"\n[SUMO] Starting simulation: {sumocfg_path.name}")
        print(f"       Binary  : {sumo_binary}")
        print(f"       Warm-up : {warmup_steps:,} steps  "
              f"({warmup_steps * step_length:.1f} s)")
        print(f"       Sampling: {sampling_steps:,} steps  "
              f"({sampling_steps * step_length:.1f} s)")
        print(f"       Output  : {raw_steps_dir}")

    traci.start(sumo_cmd)
    try:
        _simulation_loop(
            raw_steps_dir,
            total_steps,
            warmup_steps,
            sampling_steps,
            verbose,
        )
    finally:
        traci.close()

    if verbose:
        print("[SUMO] Simulation complete.")

    return raw_steps_dir


# ---------------------------------------------------------------------------
# Internal loop
# ---------------------------------------------------------------------------

def _simulation_loop(
    raw_steps_dir: Path,
    total_steps: int,
    warmup_steps: int,
    sampling_steps: int,
    verbose: bool,
):
    """Core TraCI loop.  Saves a CSV for every step in the sampling window."""

    sampling_start = warmup_steps        # first step to record (exclusive lower bound)
    sampling_end   = warmup_steps + sampling_steps  # last step to record (inclusive)

    for step in range(total_steps + 1):
        traci.simulationStep()

        # ---- Collect positions for every participant -------------------------
        location_list = []

        for vid in traci.vehicle.getIDList():
            x, y = traci.vehicle.getPosition(vid)
            location_list.append([
                vid,
                round(x, 3),
                round(y, 3),
                traci.vehicle.getTypeID(vid),
                round(traci.vehicle.getSpeed(vid), 3),
                round(traci.vehicle.getAngle(vid), 3),
            ])

        for pid in traci.person.getIDList():
            x, y = traci.person.getPosition(pid)
            location_list.append([
                pid,
                round(x, 3),
                round(y, 3),
                traci.person.getTypeID(pid),
                round(traci.person.getSpeed(pid), 3),
                round(traci.person.getAngle(pid), 3),
            ])

        # ---- Write CSV during sampling window --------------------------------
        if sampling_start < step <= sampling_end:
            csv_path = raw_steps_dir / f"location_step_{step}.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerows(location_list)

        # ---- Progress reporting ---------------------------------------------
        if verbose and step % 10_000 == 0:
            phase = "WARMUP" if step <= warmup_steps else "SAMPLING"
            n_veh = len(traci.vehicle.getIDList())
            n_ped = len(traci.person.getIDList())
            pct   = 100.0 * step / total_steps
            print(
                f"  [{phase}] step {step:>8,} / {total_steps:,}  "
                f"({pct:5.1f}%)  vehicles: {n_veh}  persons: {n_ped}"
            )
