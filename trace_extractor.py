"""
trace_extractor.py
~~~~~~~~~~~~~~~~~~
Reads the per-timestep raw CSV files produced by sumo_runner.py, filters for
participants that were present throughout an entire analysis batch, and writes
consolidated trace files for use in any mobility simulator.

Output file format (one CSV per batch):
    time_step, x, y, type_id, speed, angle

This is a refactored, parametric version of the original observed_vehicles_to_csv.py.
"""

import csv
import math
import multiprocessing
import os
import shutil
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
) -> tuple:
    """Filter and consolidate raw per-step CSVs into generated_traces files.

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
    Tuple of:
      - List of Path objects for the generated trace files.
      - List of int persistent-participant counts, one per generated file.
    """
    raw_steps_dir = Path(raw_steps_dir)
    output_dir    = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    n_batches        = math.ceil(sampling_steps / batch_size)
    output_paths     = []
    persistent_counts = []

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
        persistent_counts.append(len(staying_ids))

    if verbose:
        print(f"[EXTRACT] Done.  {len(output_paths)} trace file(s) written to {output_dir}")

    return output_paths, persistent_counts


# ---------------------------------------------------------------------------
# Parallel extraction
# ---------------------------------------------------------------------------

def _worker_extract_batches(args: dict) -> list:
    """Top-level worker for parallel extraction (module-level for pickling).

    Returns a list of ``(batch_idx, n_persistent, csv_path_str)`` tuples,
    one for each successfully processed batch in this worker's assignment.
    """
    raw_steps_dir  = Path(args["raw_steps_dir"])
    temp_dir       = Path(args["temp_dir"])
    warmup_steps   = args["warmup_steps"]
    batch_size     = args["batch_size"]
    sampling_steps = args["sampling_steps"]
    batch_indices  = args["batch_indices"]
    worker_id      = args["worker_id"]

    results = []
    for batch_idx in batch_indices:
        batch_start = warmup_steps + batch_idx * batch_size + 1
        batch_end   = min(warmup_steps + (batch_idx + 1) * batch_size,
                         warmup_steps + sampling_steps)

        frames = []
        for step in range(batch_start, batch_end + 1):
            csv_path = raw_steps_dir / f"location_step_{step}.csv"
            if not csv_path.exists():
                frames = []
                break
            df = pd.read_csv(csv_path, header=None,
                             names=["id", "x", "y", "type", "speed", "angle"])
            df["_step_idx"] = step - batch_start
            frames.append(df)

        if not frames:
            continue

        id_sets     = [set(df["id"]) for df in frames]
        staying_ids = id_sets[0].intersection(*id_sets[1:])
        if not staying_ids:
            continue

        rows = []
        for df in frames:
            mask = df["id"].isin(staying_ids)
            rows.append(df.loc[mask, ["_step_idx", "x", "y", "type", "speed", "angle"]])

        combined = pd.concat(rows, ignore_index=True)
        combined.sort_values("_step_idx", inplace=True)

        out_path = temp_dir / f"tmp_w{worker_id}_b{batch_idx}.csv"
        combined.to_csv(out_path, index=False, header=False)
        results.append((batch_idx, len(staying_ids), str(out_path)))

    return results


def extract_traces_parallel(
    raw_steps_dir: str | os.PathLike,
    output_dir: str | os.PathLike,
    n_workers: int,
    warmup_steps: int   = config.DEFAULT_WARMUP_STEPS,
    sampling_steps: int = config.DEFAULT_SAMPLING_STEPS,
    batch_size: int     = 10_000,
    verbose: bool       = True,
) -> tuple:
    """Parallel version of :func:`extract_traces`.

    Distributes batches across *n_workers* processes, then concatenates all
    results into a single ``traces.csv`` file in *output_dir*.

    Returns the same ``(output_paths, persistent_counts)`` tuple as
    :func:`extract_traces`, but *output_paths* is always a one-element list.
    """
    raw_steps_dir = Path(raw_steps_dir)
    output_dir    = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_dir  = output_dir / "_parallel_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    n_batches   = math.ceil(sampling_steps / batch_size)
    all_indices = list(range(n_batches))

    # Distribute batch indices round-robin across workers
    worker_batches: list[list[int]] = [[] for _ in range(n_workers)]
    for i, idx in enumerate(all_indices):
        worker_batches[i % n_workers].append(idx)

    worker_args = [
        {
            "raw_steps_dir" : str(raw_steps_dir),
            "temp_dir"      : str(temp_dir),
            "warmup_steps"  : warmup_steps,
            "batch_size"    : batch_size,
            "sampling_steps": sampling_steps,
            "batch_indices" : worker_batches[w],
            "worker_id"     : w,
        }
        for w in range(n_workers)
        if worker_batches[w]
    ]

    if verbose:
        print(f"\n[EXTRACT-PARALLEL] Source  : {raw_steps_dir}")
        print(f"                   Output  : {output_dir}")
        print(f"                   Batches : {n_batches}  across {n_workers} workers")

    with multiprocessing.Pool(processes=n_workers) as pool:
        worker_results = pool.map(_worker_extract_batches, worker_args)

    # Flatten and sort by batch_idx
    flat = sorted(
        [item for sublist in worker_results for item in sublist],
        key=lambda x: x[0],
    )

    persistent_counts = [r[1] for r in flat]
    temp_files        = [Path(r[2]) for r in flat]

    if not temp_files:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if verbose:
            print("[EXTRACT-PARALLEL] No persistent participants found in any batch.")
        return [], []

    if verbose:
        print(f"[EXTRACT-PARALLEL] Merging {len(temp_files)} batch file(s) …")

    # Concatenate all temp CSVs into one traces.csv
    out_path = output_dir / "traces.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fout:
        for tfile in temp_files:
            with open(tfile, "r", encoding="utf-8") as fin:
                fout.write(fin.read())

    shutil.rmtree(temp_dir, ignore_errors=True)

    if verbose:
        avg = sum(persistent_counts) / len(persistent_counts)
        print(f"[EXTRACT-PARALLEL] Done.  Combined trace written to {out_path}")
        print(f"                   {len(flat)} batch(es), "
              f"avg {avg:.0f} persistent participants/batch")

    return [out_path], persistent_counts
