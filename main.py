"""
main.py
~~~~~~~
Interactive CLI for the VRU Urban Traffic Generator.

Workflow
--------
  1. User inputs target density (users/km²).
  2. App proposes a participant distribution (cars, pedestrians, cyclists,
     motorcyclists) matching that density.
  3. User confirms the proposal or overrides individual counts using a
     compact syntax:   -p N   -c N   -m N   -v N
  4. User configures optional simulation timing parameters.
  5. App generates SUMO scenario files (.rou.xml + .sumocfg).
  6. App asks to run the SUMO simulation.
  7. App asks to extract trace CSV files.

Usage
-----
    python main.py
"""

import argparse
import math
import os
import re
import sys
from pathlib import Path

import config
import scenario_generator as sg


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_SEP   = "─" * 62
_BOLD  = "\033[1m"
_RESET = "\033[0m"
_WARN  = "\033[33m"   # yellow
_OK    = "\033[32m"   # green
_ERR   = "\033[31m"   # red


def _hdr(text: str):
    print(f"\n{_BOLD}{text}{_RESET}")
    print(_SEP)


def _warn(text: str):
    print(f"{_WARN}⚠  {text}{_RESET}")


def _ok(text: str):
    print(f"{_OK}✔  {text}{_RESET}")


def _err(text: str):
    print(f"{_ERR}✖  {text}{_RESET}")


def _table(distribution: dict, stats: dict):
    """Pretty-print the distribution + density table."""
    cars  = distribution["cars"]
    ped   = distribution["pedestrians"]
    bike  = distribution["cyclists"]
    moto  = distribution["motorcyclists"]
    total = stats["total"]
    vru   = stats["vru"]

    def pct(n, of):
        return f"{100.0*n/of:.1f}%" if of > 0 else "—"

    print(f"  Network area : {config.SUMO_AREA_KM2} km²")
    print(f"  Total users  : {total}   →   {stats['density_km2']:,.0f} users/km²\n")
    print(f"  {'Agent':<22} {'Count':>7}   {'% of VRU':>10}")
    print(f"  {'─'*22}   {'─'*7}   {'─'*10}")
    print(f"  {'Cars (vehicles)':<22} {cars:>7}   {'—':>10}")
    print(f"  {'Pedestrians':<22} {ped:>7}   {pct(ped, vru):>10}")
    print(f"  {'Cyclists':<22} {bike:>7}   {pct(bike, vru):>10}")
    print(f"  {'Motorcyclists':<22} {moto:>7}   {pct(moto, vru):>10}")
    print(f"  {'─'*22}   {'─'*7}   {'─'*10}")
    print(f"  {'TOTAL':<22} {total:>7}")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _ask_density() -> float:
    """Prompt the user for a target density and return it as a float."""
    while True:
        raw = input("\n  Enter target density (users/km²) [e.g. 2000]: ").strip()
        try:
            val = float(raw)
            if val <= 0:
                _err("Density must be a positive number.")
                continue
            return val
        except ValueError:
            _err("Please enter a numeric value.")


def _parse_override(text: str) -> dict | None:
    """Parse a string like '-p 200 -c 80 -m 10 -v 120' into a counts dict.

    Any flag not present retains None (meaning: keep the proposed value).
    Returns None if the string contains unrecognised tokens.
    """
    mapping = {"p": "pedestrians", "c": "cyclists", "m": "motorcyclists", "v": "cars"}
    result  = {}
    tokens  = text.split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if re.fullmatch(r"-[pcmv]", token):
            key = mapping[token[1]]
            if i + 1 >= len(tokens):
                _err(f"Flag '{token}' has no value.")
                return None
            try:
                val = int(tokens[i + 1])
                if val < 0:
                    _err(f"Count for '{token}' must be >= 0.")
                    return None
                result[key] = val
                i += 2
            except ValueError:
                _err(f"'{tokens[i+1]}' is not a valid integer for flag '{token}'.")
                return None
        else:
            _err(f"Unknown token '{token}'.  "
                 "Valid flags: -p (pedestrians) -c (cyclists) -m (motorcyclists) -v (cars).")
            return None
    return result


def _ask_distribution(proposal: dict) -> dict:
    """Show the proposed distribution and let the user confirm or override."""
    print(
        "\n  Press ENTER to accept the proposal, or enter custom counts using:\n"
        f"  {_BOLD}-p N  -c N  -m N  -v N{_RESET}   "
        "(p=pedestrians, c=cyclists, m=motorcyclists, v=cars)"
    )
    while True:
        raw = input("\n  > ").strip()
        if raw == "":
            return proposal.copy()

        overrides = _parse_override(raw)
        if overrides is None:
            continue   # error already printed; re-prompt

        distribution = {**proposal, **overrides}
        warnings = sg.validate_distribution(
            distribution["cars"],
            distribution["pedestrians"],
            distribution["cyclists"],
            distribution["motorcyclists"],
        )
        if warnings:
            for w in warnings:
                _warn(w)
            cont = input("  Continue with this distribution? [y/N]: ").strip().lower()
            if cont != "y":
                continue

        stats = sg.density_stats(
            distribution["cars"],
            distribution["pedestrians"],
            distribution["cyclists"],
            distribution["motorcyclists"],
        )
        print()
        _table(distribution, stats)
        confirm = input("\n  Confirm this distribution? [Y/n]: ").strip().lower()
        if confirm != "n":
            return distribution


def _ask_sim_params() -> dict:
    """Ask the user for optional simulation timing overrides."""
    print(
        f"\n  Simulation timing defaults:"
        f"\n    Step size: {config.STEP_LENGTH} s"
        f"\n    Warm-up  : {config.DEFAULT_WARMUP_S} s  ({config.DEFAULT_WARMUP_STEPS:,} steps)"
        f"\n    Sampling : {config.DEFAULT_SAMPLING_S} s  ({config.DEFAULT_SAMPLING_STEPS:,} steps)"
    )
    change = input("\n  Change timing parameters? [y/N]: ").strip().lower()
    if change != "y":
        return {
            "step_length"   : config.STEP_LENGTH,
            "warmup_steps"  : config.DEFAULT_WARMUP_STEPS,
            "sampling_steps": config.DEFAULT_SAMPLING_STEPS,
        }

    step_length = _ask_positive_float(
        f"  Step size (seconds) [{config.STEP_LENGTH}]: ",
        default=config.STEP_LENGTH,
    )
    warmup_s = _ask_positive_float(
        f"  Warm-up duration (seconds) [{config.DEFAULT_WARMUP_S}]: ",
        default=config.DEFAULT_WARMUP_S,
    )
    sampling_s = _ask_positive_float(
        f"  Sampling duration (seconds) [{config.DEFAULT_SAMPLING_S}]: ",
        default=config.DEFAULT_SAMPLING_S,
    )
    return {
        "step_length"   : step_length,
        "warmup_steps"  : int(warmup_s   / step_length),
        "sampling_steps": int(sampling_s / step_length),
    }


def _ask_positive_float(prompt: str, default: float) -> float:
    while True:
        raw = input(prompt).strip()
        if raw == "":
            return default
        try:
            val = float(raw)
            if val > 0:
                return val
            _err("Value must be > 0.")
        except ValueError:
            _err("Please enter a numeric value.")


def _ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    hint = "[Y/n]" if default_yes else "[y/N]"
    raw  = input(f"{prompt} {hint}: ").strip().lower()
    if raw == "":
        return default_yes
    return raw == "y"


def _fmt_time(seconds: float) -> str:
    """Format a duration in seconds as a compact human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f} s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s:02d}s"
    else:
        h, rem = divmod(int(seconds), 3600)
        m = rem // 60
        return f"{h}h {m:02d}m"


# ---------------------------------------------------------------------------
# Parallel simulation worker  (module-level so multiprocessing can pickle it)
# ---------------------------------------------------------------------------

def _run_sim_extract_worker(args: tuple):
    """Run one SUMO simulation slice and extract its traces.

    In parallel speed mode each worker simulates the full warm-up plus a slice
    of the sampling window; seed=None so SUMO picks its own random state.
    In multiple-run mode a distinct integer seed is supplied so each run
    produces statistically independent traffic patterns.
    Extraction happens immediately after simulation inside the same process.

    Args tuple: (worker_id, cfg_path_str, worker_dir_str,
                 warmup_steps, sampling_steps, step_length, seed)

    Returns: (list[str] of trace file paths, list[int] of persistent counts)
    """
    (worker_id, cfg_path_str, worker_dir_str,
     warmup_steps, sampling_steps, step_length, seed) = args

    from pathlib import Path as _Path
    from sumo_runner import run_simulation
    from trace_extractor import extract_traces

    worker_dir = _Path(worker_dir_str)

    raw_steps_dir = run_simulation(
        sumocfg_path   = cfg_path_str,
        output_dir     = worker_dir,
        warmup_steps   = warmup_steps,
        sampling_steps = sampling_steps,
        step_length    = step_length,
        use_gui        = False,
        verbose        = False,
        seed           = seed,
    )

    traces_dir = worker_dir / "generated_traces"
    output_files, persistent_counts = extract_traces(
        raw_steps_dir  = raw_steps_dir,
        output_dir     = traces_dir,
        warmup_steps   = warmup_steps,
        sampling_steps = sampling_steps,
        verbose        = False,
    )

    return [str(p) for p in output_files], persistent_counts


def _ask_positive_int(prompt: str, default: int) -> int:
    while True:
        raw = input(prompt).strip()
        if raw == "":
            return default
        try:
            val = int(raw)
            if val >= 1:
                return val
            _err("Value must be >= 1.")
        except ValueError:
            _err("Please enter an integer.")


def _ask_runs() -> int:
    """Ask how many independent runs to produce.

    Each run uses a distinct SUMO random seed so traffic patterns differ,
    enabling statistical replication over the same simulation period and
    distribution.
    """
    n = _ask_positive_int(
        "\n  Number of independent runs [1]: ", default=1
    )
    if n > 1:
        _warn(f"{n} runs requested – each will use a unique SUMO random seed.")
        print(f"  Outputs will be saved in: run_1/  run_2/ … run_{n}/")
    return n


def _get_hw_profile() -> dict:
    """Return CPU GHz and RAM GB for the current machine via psutil."""
    try:
        import psutil
        freq   = psutil.cpu_freq()
        cpu_hz = freq.current if (freq and freq.current) else (freq.max if freq else 3000)
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        return {"cpu_ghz": cpu_hz / 1000, "ram_gb": ram_gb}
    except Exception:
        return {"cpu_ghz": 3.0, "ram_gb": 8.0}


def _estimate_times(
    total_participants: int,
    warmup_steps: int,
    sampling_steps: int,
    n_workers: int,
    hw: dict,
    step_length: float = config.STEP_LENGTH,
) -> dict:
    """Hardware-aware, 3-phase wall-clock time estimates.

    Calibration reference (measured on user's machine):
      ~286 active agents at step=0.001 s  →  ~62 ms/step wall clock
      (SUMO log: 20 ms simulation + 42 ms TraCI per step)
      Verified: 8 500 steps × 62 ms ≈ 527 s ≈ "roughly 7 minutes".

    With the injection-window approach all agent types enter between t=0 and
    t=FLOW_INJECT_WINDOW_S, so the three phases are:

      Phase 1 – injection window (t=0 → FLOW_INJECT_WINDOW_S)
        All types ramp from 0 to target count simultaneously.
        avg_agents ≈ total × 0.50.

      Phase 2 – post-injection stabilisation
        Agents spread and reach naturalistic positions/speeds.
        avg_agents ≈ total × 0.95.

      Phase 3 – sampling window (steady state + one CSV write per step)
        All participants active; I/O cost added on top of SUMO cost.

    All cost constants are scaled by cpu_ghz / 3.5 (reference machine).
    """
    cpu_scale = hw["cpu_ghz"] / 3.5
    ram_gb    = hw["ram_gb"]

    # Per-step SUMO + TraCI cost (ms), calibrated at 3.5 GHz:
    #   base   = 20 ms (SUMO computation) + ~7 ms TraCI framework = 27 ms
    #   at 286 agents total = 62 ms  →  per_agent = (62−27)/286 ≈ 0.122 ms
    base_ms      = 27.0 / cpu_scale
    per_agent_ms = 0.122 / cpu_scale

    inject_steps = int(config.FLOW_INJECT_WINDOW_S / step_length)

    # Phase 1: injection window — all agent types entering simultaneously
    ph1_steps      = min(inject_steps, warmup_steps)
    avg_agents_ph1 = total_participants * 0.50
    ph1_ms         = ph1_steps * (base_ms + per_agent_ms * avg_agents_ph1)

    # Phase 2: stabilisation after injection ends
    ph2_steps      = max(0, warmup_steps - ph1_steps)
    avg_agents_ph2 = total_participants * 0.95
    ph2_ms         = ph2_steps * (base_ms + per_agent_ms * avg_agents_ph2)

    # Phase 3: sampling window — steady state + CSV write per step
    io_ms  = (0.10 + total_participants * 1.40e-3) / cpu_scale
    ph3_ms = sampling_steps * (base_ms + per_agent_ms * total_participants + io_ms)

    sim_s = (ph1_ms + ph2_ms + ph3_ms) / 1000

    # Parallel simulation: each worker does full warmup + sampling/n_workers steps.
    sampling_per_worker = math.ceil(sampling_steps / n_workers)
    par_ph3_ms = sampling_per_worker * (base_ms + per_agent_ms * total_participants + io_ms)
    par_sim_s  = (ph1_ms + ph2_ms + par_ph3_ms) / 1000

    # Extraction cost
    ram_scale              = min(1.0, ram_gb / 8.0)
    time_per_step          = (2.0e-4 + total_participants * 3.0e-6) / ram_scale
    seq_extract_s          = sampling_steps * time_per_step
    par_extract_per_worker = sampling_per_worker * time_per_step

    return {
        "sim_s"        : sim_s,
        "par_sim_s"    : par_sim_s,
        "seq_extract_s": seq_extract_s,
        "par_extract_s": par_extract_per_worker,
        "seq_total_s"  : sim_s + seq_extract_s,
        "par_total_s"  : par_sim_s + par_extract_per_worker,
    }


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*62}")
    print(f"  {_BOLD}VRU Urban Traffic Generator{_RESET}")
    print(f"  ETSI TR 138.913 Urban Scenario  ·  SUMO")
    print(f"{'='*62}")

    # ------------------------------------------------------------------
    # Step 1 – Target density
    # ------------------------------------------------------------------
    _hdr("Step 1 – Target Density")
    density = _ask_density()

    # ------------------------------------------------------------------
    # Step 2 – Proposed distribution
    # ------------------------------------------------------------------
    _hdr("Step 2 – Proposed Distribution")
    proposal = sg.propose_distribution(density)
    stats    = sg.density_stats(**proposal)
    _table(proposal, stats)

    # ------------------------------------------------------------------
    # Step 3 – Confirm or override
    # ------------------------------------------------------------------
    _hdr("Step 3 – Confirm / Override Distribution")
    distribution = _ask_distribution(proposal)

    # Final stats
    final_stats = sg.density_stats(
        distribution["cars"],
        distribution["pedestrians"],
        distribution["cyclists"],
        distribution["motorcyclists"],
    )
    print()
    _ok(f"Distribution confirmed  –  {final_stats['total']} users  "
        f"({final_stats['density_km2']:,.0f} users/km²)")

    # ------------------------------------------------------------------
    # Step 4 – Simulation timing
    # ------------------------------------------------------------------
    _hdr("Step 4 – Simulation Parameters")
    sim_params = _ask_sim_params()
    n_runs = _ask_runs()

    # ------------------------------------------------------------------
    # Step 5 – Generate SUMO scenario files
    # ------------------------------------------------------------------
    _hdr("Step 5 – Generate SUMO Scenario")
    cars  = distribution["cars"]
    ped   = distribution["pedestrians"]
    bike  = distribution["cyclists"]
    moto  = distribution["motorcyclists"]

    scene_name  = sg.scenario_name(cars, ped, bike, moto)
    project_root = Path(__file__).parent
    scenario_dir = project_root / config.SCENARIOS_DIR / scene_name

    print(f"\n  Scenario name : {scene_name}")
    print(f"  Output folder : {scenario_dir}")

    rou_path, cfg_path = sg.generate_scenario(
        cars, ped, bike, moto,
        scenario_dir=scenario_dir,
        step_length=sim_params["step_length"],
    )
    _ok(f"Route file  : {rou_path.name}")
    _ok(f"Config file : {cfg_path.name}")

    # ------------------------------------------------------------------
    # Step 6 – Run SUMO Simulation
    # ------------------------------------------------------------------
    _hdr("Step 6 – Run SUMO Simulation")
    total_participants = (distribution["cars"] + distribution["pedestrians"]
                          + distribution["cyclists"] + distribution["motorcyclists"])
    total_steps_all = sim_params["warmup_steps"] + sim_params["sampling_steps"]
    total_sim_s     = total_steps_all * sim_params["step_length"]
    run_label = f"{n_runs} independent run{'s' if n_runs > 1 else ''}"
    print(f"\n  This will run SUMO for ~{total_sim_s:.0f} s of simulation time "
          f"({run_label}).")

    # --- Parallel computation decision -----------------------------------
    n_cpu        = os.cpu_count() or 1
    n_workers    = max(1, n_cpu - 1)
    is_heavy     = (total_participants > 500)
    use_parallel = False

    if n_workers >= 2 and is_heavy:
        hw  = _get_hw_profile()
        eta = _estimate_times(
            total_participants,
            sim_params["warmup_steps"],
            sim_params["sampling_steps"],
            n_workers,
            hw,
            step_length=sim_params["step_length"],
        )
        runs_note = f"  ×{n_runs} runs" if n_runs > 1 else ""
        print(f"\n  {_WARN}⚑  Heavy scenario detected{_RESET}  "
              f"({total_participants} participants, "
              f"step = {sim_params['step_length']} s{runs_note})")
        print(f"  Hardware : {hw['cpu_ghz']:.2f} GHz CPU · "
              f"{hw['ram_gb']:.1f} GB RAM · "
              f"{n_cpu} cores → {n_workers} workers available")
        col = 32
        print(f"\n  {'Mode':<{col}}  {'Simulation':>11}  {'Extraction':>11}  {'Total (per run)':>15}")
        print(f"  {'─'*col}  {'─'*11}  {'─'*11}  {'─'*15}")
        print(f"  {'Sequential  (1 worker)':<{col}}  "
              f"{_fmt_time(eta['sim_s']):>11}  "
              f"{_fmt_time(eta['seq_extract_s']):>11}  "
              f"{_fmt_time(eta['seq_total_s']):>15}")
        print(f"  {f'Parallel    ({n_workers} workers)':<{col}}  "
              f"{_fmt_time(eta['par_sim_s']):>11}  "
              f"{_fmt_time(eta['par_extract_s']):>11}  "
              f"{_fmt_time(eta['par_total_s']):>15}")
        print(f"  {_WARN}Note: parallel splits the sampling window across {n_workers} SUMO")
        print(f"  instances (each does the full warm-up); extraction is embedded in each worker.{_RESET}")
        if n_runs > 1:
            print(f"  {_WARN}Multiple runs: the above totals are per run × {n_runs} runs.{_RESET}")
        print(f"  {_WARN}Cloud-synced paths (OneDrive, Google Drive) may be significantly slower.{_RESET}")
        use_parallel = _ask_yes_no(
            f"\n  Use parallel simulation ({n_workers} SUMO instances) for speed?",
            default_yes=True,
        )

    # --- Pre-run confirmation --------------------------------------------
    do_extract = True
    use_gui    = False
    if use_parallel:
        _ok(f"Parallel mode: {n_workers} SUMO instances will split each sampling window.")
        launch_label = (
            f"all {n_runs} runs × {n_workers} workers"
            if n_runs > 1 else f"{n_workers} workers"
        )
        if not _ask_yes_no(f"  Launch {launch_label}?", default_yes=True):
            print("\n  Skipping.  Run manually with:")
            print(f"    sumo -c \"{cfg_path}\"")
            return
    else:
        use_gui = _ask_yes_no("  Use SUMO GUI?", default_yes=False)
        if not _ask_yes_no("  Run SUMO now?"):
            binary = "sumo-gui" if use_gui else "sumo"
            print("\n  Skipping simulation.  You can run it later with:")
            print(f"    {binary} -c \"{cfg_path}\"")
            return
        if n_runs == 1:
            do_extract = _ask_yes_no(
                "  Extract traces immediately after simulation?",
                default_yes=True,
            )

    # Lazy imports (keeps startup fast for users who only generate files)
    try:
        from sumo_runner import run_simulation
    except EnvironmentError as exc:
        _err(str(exc))
        return
    from trace_extractor import extract_traces

    # --- Run loop --------------------------------------------------------
    all_output_files     : list = []
    all_persistent_counts: list = []
    traces_dir = None

    for run_idx in range(n_runs):
        # Seed: only matters for multiple runs (statistical independence).
        # Parallel speed-mode workers receive this same seed (or None for
        # a single run) – they are partitioning one period, not replicating.
        run_seed = run_idx + 1 if n_runs > 1 else None
        if n_runs > 1:
            print(f"\n  {'─'*62}")
            print(f"  Run {run_idx + 1} / {n_runs}  (SUMO seed = {run_seed})")
            print(f"  {'─'*62}")
        run_dir = (
            scenario_dir / f"run_{run_idx + 1}"
            if n_runs > 1 else scenario_dir
        )

        if use_parallel:
            sampling_per_worker = math.ceil(sim_params["sampling_steps"] / n_workers)
            worker_args = [
                (
                    i,
                    str(cfg_path),
                    str(run_dir / f"worker_{i}"),
                    sim_params["warmup_steps"],
                    sampling_per_worker,
                    sim_params["step_length"],
                    run_seed,   # None for single run; distinct seed per multiple run
                )
                for i in range(n_workers)
            ]
            print(f"\n  Launching {n_workers} SUMO instances in parallel …")
            from multiprocessing import Pool
            with Pool(n_workers) as pool:
                results = pool.map(_run_sim_extract_worker, worker_args)
            print(f"  All {n_workers} workers completed.  Merging traces …")

            import pandas as pd
            merged_dir = run_dir / "generated_traces"
            merged_dir.mkdir(parents=True, exist_ok=True)
            all_dfs = []
            for worker_files, _ in results:
                for fpath_str in worker_files:
                    try:
                        all_dfs.append(pd.read_csv(fpath_str, header=None))
                    except Exception:
                        pass
            if all_dfs:
                merged_path = merged_dir / "traces.csv"
                pd.concat(all_dfs, ignore_index=True).to_csv(
                    merged_path, index=False, header=False
                )
                output_files = [merged_path]
            else:
                output_files = []
            persistent_counts = [c for _, counts in results for c in counts]
            traces_dir = merged_dir

        else:
            raw_steps_dir = run_simulation(
                sumocfg_path   = cfg_path,
                output_dir     = run_dir,
                warmup_steps   = sim_params["warmup_steps"],
                sampling_steps = sim_params["sampling_steps"],
                step_length    = sim_params["step_length"],
                use_gui        = use_gui,
                seed           = run_seed,
            )

            if n_runs == 1:
                _hdr("Step 7 – Extract Traces")
            print(f"\n  Raw step files are in: {raw_steps_dir}")
            if not do_extract:
                print("\n  Skipping extraction.  Run trace_extractor.py manually later.")
                return

            traces_dir = run_dir / "generated_traces"
            output_files, persistent_counts = extract_traces(
                raw_steps_dir  = raw_steps_dir,
                output_dir     = traces_dir,
                warmup_steps   = sim_params["warmup_steps"],
                sampling_steps = sim_params["sampling_steps"],
            )

        all_output_files.extend(output_files)
        all_persistent_counts.extend(persistent_counts)

    output_files      = all_output_files
    persistent_counts = all_persistent_counts
    if traces_dir is None:
        traces_dir = scenario_dir / "generated_traces"

    print()
    for fp in output_files:
        _ok(str(fp))

    # ------------------------------------------------------------------
    # Density achievement report
    # ------------------------------------------------------------------
    _hdr("Density Achievement Report")
    expected_total = (distribution["cars"] + distribution["pedestrians"]
                      + distribution["cyclists"] + distribution["motorcyclists"])
    expected_density = expected_total / config.SUMO_AREA_KM2

    if persistent_counts:
        avg_persistent   = sum(persistent_counts) / len(persistent_counts)
        max_persistent   = max(persistent_counts)
        avg_density      = avg_persistent / config.SUMO_AREA_KM2
        ratio            = avg_persistent / expected_total if expected_total > 0 else 0.0

        print(f"\n  Expected participants : {expected_total}  "
              f"({expected_density:,.0f} users/km²)")
        print(f"  Avg persistent/batch : {avg_persistent:.1f}  "
              f"({avg_density:,.0f} users/km²)  "
              f"[best batch: {max_persistent}]")

        if ratio >= 0.90:
            _ok(f"Target density reached  ({ratio*100:.1f}% of expected participants "
                f"are persistent across each batch).")
        elif ratio >= 0.70:
            print(f"\033[33m⚠  Partial density reached ({ratio*100:.1f}% of expected "
                  f"participants persistent).  Consider:\033[0m")
            print(f"\033[33m   • Increasing warm-up time (current: "
                  f"{sim_params['warmup_steps'] * sim_params['step_length']:.0f} s) "
                  f"so more agents reach steady state before sampling.\033[0m")
            print(f"\033[33m   • Reducing the batch / sampling window so fewer agents "
                  f"leave mid-batch.\033[0m")
        else:
            print(f"\033[31m✖  Target density NOT reached ({ratio*100:.1f}% of expected "
                  f"participants persistent).  Action required:\033[0m")
            print(f"\033[31m   • Increase warm-up time (current: "
                  f"{sim_params['warmup_steps'] * sim_params['step_length']:.0f} s) – "
                  f"agents need more time to enter and stabilise.\033[0m")
            print(f"\033[31m   • Reduce sampling window (current: "
                  f"{sim_params['sampling_steps'] * sim_params['step_length']:.0f} s) "
                  f"to keep more agents persistent throughout each batch.\033[0m")
            print(f"\033[31m   • Reduce step size to shorten batch duration "
                  f"(current: {sim_params['step_length']} s/step).\033[0m")
    else:
        print(f"\033[31m✖  No persistent participants found in any batch.  "
              f"The warm-up ({sim_params['warmup_steps'] * sim_params['step_length']:.0f} s) "
              f"may be too short – increase it and re-run.\033[0m")

    print(f"\n{'='*62}")
    _ok(f"All done!  {len(output_files)} trace file(s) in {traces_dir}")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    # Required on Windows so that spawned multiprocessing workers don't
    # re-execute the top-level script.
    import multiprocessing
    multiprocessing.freeze_support()
    main()
