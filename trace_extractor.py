"""
trace_extractor.py
~~~~~~~~~~~~~~~~~~
Reads the per-timestep raw CSV files produced by sumo_runner.py, filters for
participants that were present throughout an entire analysis batch, and writes
consolidated trace files compatible with the NR-SPS simulator.

Output file format (one CSV per batch):
    time_step, x, y, type_id, speed, angle

Columns match the format expected by the OOP_for_SPS NR-SPS simulator.

This is a refactored, parametric version of the original observed_vehicles_to_csv.py.
"""

import csv
import math
import os
from pathlib import Path

import pandas as pd

import config


def extract_traces(
    raw_steps_dir: str | os.PathLike,
    output_dir: str | os.PathLike,
    warmup_steps: int   = config.DEFAULT_WARMUP_STEPS,
    sampling_steps: int = config.DEFAULT_SAMPLING_STEPS,
    batch_size: int     = 10_000,
    verbose: bool       = True,
) -> list:
    """Filter and consolidate raw per-step CSVs into NR-SPS trace files.

    The raw step files cover steps (warmup_steps+1) … (warmup_steps+sampling_steps).
    They are processed in batches of *batch_size* steps to keep memory usage low.
    For each batch, only participants present in **every** step of that batch are
    retained – this removes transient vehicles that enter/leave mid-batch.

    Parameters
    ----------
    raw_steps_dir   : Directory containing the ``location_step_N.csv`` files
                      written by :func:`sumo_runner.run_simulation`.
    output_dir      : Directory where the consolidated trace CSVs will be saved.
    warmup_steps    : Must match the value used in :func:`sumo_runner.run_simulation`.
    sampling_steps  : Must match the value used in :func:`sumo_runner.run_simulation`.
    batch_size      : Steps per output file (default 10 000 = 10 s at 1 ms step).
    verbose         : Print progress when True.

    Returns
    -------
    List of Path objects for the generated trace files.
    """
    raw_steps_dir = Path(raw_steps_dir)
    output_dir    = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    n_batches     = math.ceil(sampling_steps / batch_size)
    output_paths  = []

    if verbose:
        print(f"\n[EXTRACT] Source : {raw_steps_dir}")
        print(f"          Output : {output_dir}")
        print(f"          Batches: {n_batches}  ×  {batch_size:,} steps")

    for batch_idx in range(n_batches):
        batch_start = warmup_steps + batch_idx * batch_size + 1
        batch_end   = min(warmup_steps + (batch_idx + 1) * batch_size,
                         warmup_steps + sampling_steps)
        steps_in_batch = batch_end - batch_start + 1

        if verbose:
            pct = 100.0 * batch_idx / n_batches
            print(f"  [{pct:5.1f}%] Batch {batch_idx}/{n_batches}  "
                  f"steps {batch_start:,} – {batch_end:,} …", end=" ", flush=True)

        # --- Load all frames for this batch ----------------------------------
        frames     = []
        step_range = range(batch_start, batch_end + 1)
        for step in step_range:
            csv_path = raw_steps_dir / f"location_step_{step}.csv"
            if not csv_path.exists():
                if verbose:
                    print(f"\n  [WARN] Missing file: {csv_path.name} – skipping batch.")
                frames = []
                break
            df = pd.read_csv(csv_path, header=None,
                             names=["id", "x", "y", "type", "speed", "angle"])
            df["_step_idx"] = step - batch_start   # 0-based index within batch
            frames.append(df)

        if not frames:
            continue

        # --- Find participants present in ALL steps of this batch ------------
        id_sets           = [set(df["id"]) for df in frames]
        staying_ids       = id_sets[0].intersection(*id_sets[1:])

        if verbose:
            print(f"{len(staying_ids):,} persistent participants.")

        if not staying_ids:
            continue

        # --- Collect observations for persistent participants ----------------
        rows = []
        for df in frames:
            mask = df["id"].isin(staying_ids)
            sub  = df.loc[mask, ["_step_idx", "x", "y", "type", "speed", "angle"]]
            rows.append(sub)

        combined = pd.concat(rows, ignore_index=True)
        combined.sort_values(["_step_idx", "id"] if "id" in combined.columns
                             else "_step_idx", inplace=True)

        # --- Write output CSV ------------------------------------------------
        out_path = output_dir / f"traces_batch_{batch_idx}.csv"
        combined.to_csv(out_path, index=False, header=False)
        output_paths.append(out_path)

    if verbose:
        print(f"[EXTRACT] Done.  {len(output_paths)} trace file(s) written to {output_dir}")

    return output_paths
