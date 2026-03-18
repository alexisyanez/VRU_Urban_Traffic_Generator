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
    # Step 6 – Run SUMO simulation
    # ------------------------------------------------------------------
    _hdr("Step 6 – Run SUMO Simulation")
    total_sim_s = (sim_params["warmup_steps"] + sim_params["sampling_steps"]) * sim_params["step_length"]
    print(f"\n  This will run SUMO for ~{total_sim_s:.0f} s of simulation time.")

    use_gui = _ask_yes_no("  Use SUMO GUI?", default_yes=False)

    if not _ask_yes_no("  Run SUMO now?"):
        binary = "sumo-gui" if use_gui else "sumo"
        print("\n  Skipping simulation.  You can run it later with:")
        print(f"    {binary} -c \"{cfg_path}\"")
        return

    # Lazy import so that users who only want to generate files don't need TraCI
    try:
        from sumo_runner import run_simulation
    except EnvironmentError as exc:
        _err(str(exc))
        return

    raw_steps_dir = run_simulation(
        sumocfg_path  = cfg_path,
        output_dir    = scenario_dir,
        warmup_steps  = sim_params["warmup_steps"],
        sampling_steps= sim_params["sampling_steps"],
        step_length   = sim_params["step_length"],
        use_gui       = use_gui,
    )

    # ------------------------------------------------------------------
    # Step 7 – Extract traces
    # ------------------------------------------------------------------
    _hdr("Step 7 – Extract Traces")
    print(f"\n  Raw step files are in: {raw_steps_dir}")
    if not _ask_yes_no("  Extract trace CSVs now?"):
        print("\n  Skipping extraction.  Run trace_extractor.py manually later.")
        return

    from trace_extractor import extract_traces

    traces_dir  = scenario_dir / "generated_traces"
    output_files, persistent_counts = extract_traces(
        raw_steps_dir  = raw_steps_dir,
        output_dir     = traces_dir,
        warmup_steps   = sim_params["warmup_steps"],
        sampling_steps = sim_params["sampling_steps"],
    )

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
    main()
