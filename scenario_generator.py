"""
scenario_generator.py
~~~~~~~~~~~~~~~~~~~~~
Converts user-supplied participant counts into SUMO route (.rou.xml) and
configuration (.sumocfg) files, and computes density statistics.

Key public functions
--------------------
propose_distribution(density_km2)            -> dict
validate_distribution(cars, ped, bike, moto) -> list[str]   (warnings)
generate_scenario(cars, ped, bike, moto, scenario_dir, net_file, poly_file)
    -> (rou_path, cfg_path)
density_stats(cars, pedestrians, cyclists, motorcyclists) -> dict
"""

import math
import os
from pathlib import Path

import config

# ---------------------------------------------------------------------------
# Route topology – identical across all density scenarios (V0-V19).
# Edge IDs come from ETSI TR 138.913 urban SUMO network.
# ---------------------------------------------------------------------------
_ROUTE_DEFS = [
    ("r_0",  "E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4"),
    ("r_1",  "E16 E17 -E17 -E16 E16 E17 -E17 -E16 E16 E17 -E17 -E16 E16 E17 -E17 -E16"),
    ("r_2",  "-E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5"),
    ("r_3",  "-E17 -E16 E16 E17 -E17 -E16 E16 E17 -E17 -E16 E16 E17 -E17 -E16 E16 E17"),
    ("r_4",  "E5 E4 -E4 -E5 E5 E4 -E4 -E5 E5 E4 -E4 -E5 E5 E4 -E4 -E5"),
    ("r_5",  "E17 E16 -E16 -E17 E17 E16 -E16 -E17 E17 E16 -E16 -E17 E17 E16 -E16 -E17"),
    ("r_6",  "-E4 -E5 E5 E4 -E4 -E5 E5 E4 -E4 -E5 E5 E4 -E4 -E5 E5 E4"),
    ("r_7",  "-E16 -E17 E17 E16 -E16 -E17 E17 E16 -E16 -E17 E17 E16 -E16 -E17 E17 E16"),
    ("r_8",  "E4 -E16 E16 E5 -E5 E17 -E17 -E4 E4 -E16 E16 E5 -E5 E17 -E17 -E4"),
    ("r_9",  "E16 E5 -E5 E17 -E17 -E4 E4 -E16 E16 E5 -E5 E17 -E17 -E4 E4 -E16"),
    ("r_10", "-E5 E17 -E17 -E4 E4 -E16 E16 E5 -E5 E17 -E17 -E4 E4 -E16 E16 E5"),
    ("r_11", "-E17 -E4 E4 -E16 E16 E5 -E5 E17 -E17 -E4 E4 -E16 E16 E5 -E5 E17"),
]

_ROUTE_DIST_ENTRIES = [
    ("r_c0",  "E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4",           "4"),
    ("r_c1",  "E16 E17 -E17 -E16 E16 E17 -E17 -E16 E16 E17 -E17 -E16 E16 E17 -E17 -E16",           "4"),
    ("r_c2",  "-E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5 -E5 -E4 E4 E5",           "4"),
    ("r_c3",  "-E17 -E16 E16 E17 -E17 -E16 E16 E17 -E17 -E16 E16 E17 -E17 -E16 E16 E17",           "4"),
    ("r_c8",  "E4 -E16 E16 E5 -E5 E17 -E17 -E4 E4 -E16 E16 E5 -E5 E17 -E17 -E4",                  "1"),
    ("r_c9",  "E16 E5 -E5 E17 -E17 -E4 E4 -E16 E16 E5 -E5 E17 -E17 -E4 E4 -E16",                  "1"),
    ("r_c10", "-E5 E17 -E17 -E4 E4 -E16 E16 E5 -E5 E17 -E17 -E4 E4 -E16 E16 E5",                  "1"),
    ("r_c11", "-E17 -E4 E4 -E16 E16 E5 -E5 E17 -E17 -E4 E4 -E16 E16 E5 -E5 E17",                  "1"),
]

# Pedestrian route groups with empirical weighting (ratio 2 : 3 : 1 per-flow)
# Group A: r_0..r_3  (main corridor sidewalks)
# Group B: r_4..r_7  (longer bidirectional routes, heaviest pedestrian load)
# Group C: r_8..r_11 (cross/diagonal routes)
_PED_GROUPS = [
    ("A", ["r_0", "r_1", "r_2", "r_3"],    2),   # weight 2
    ("B", ["r_4", "r_5", "r_6", "r_7"],    3),   # weight 3
    ("C", ["r_8", "r_9", "r_10", "r_11"],  1),   # weight 1
]
_PED_TOTAL_WEIGHT = sum(n * len(routes) for _, routes, n in _PED_GROUPS)  # = 4*2+4*3+4*1 = 24


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def propose_distribution(density_km2: float) -> dict:
    """Return a proposed participant count dictionary for *density_km2* users/km².

    Cars are capped at MAX_CARS.  VRUs use the DEFAULT_VRU_SPLIT fractions.
    All counts are non-negative integers.
    """
    total = max(0, round(density_km2 * config.SUMO_AREA_KM2))
    cars  = min(config.MAX_CARS, total)
    vru   = max(0, total - cars)

    ped   = round(vru * config.DEFAULT_VRU_SPLIT["pedestrian"])
    bike  = round(vru * config.DEFAULT_VRU_SPLIT["bicycle"])
    moto  = vru - ped - bike          # absorb rounding remainder

    return {"cars": cars, "pedestrians": ped, "cyclists": bike, "motorcyclists": moto}


def validate_distribution(cars: int, ped: int, bike: int, moto: int) -> list:
    """Return a (possibly empty) list of warning strings for the given counts."""
    warnings = []
    if cars > config.MAX_CARS:
        warnings.append(
            f"Cars ({cars}) exceed the recommended maximum ({config.MAX_CARS}). "
            "The road network may become saturated and SUMO could abort."
        )
    if cars < 0 or ped < 0 or bike < 0 or moto < 0:
        warnings.append("All counts must be >= 0.")
    total = cars + ped + bike + moto
    if total == 0:
        warnings.append("Total participant count is 0 – nothing to simulate.")
    return warnings


def density_stats(cars: int, pedestrians: int, cyclists: int, motorcyclists: int) -> dict:
    """Compute density metrics for a given distribution."""
    total = cars + pedestrians + cyclists + motorcyclists
    vru   = pedestrians + cyclists + motorcyclists
    return {
        "total"         : total,
        "vru"           : vru,
        "density_km2"   : round(total / config.SUMO_AREA_KM2, 1),
        "density_m2"    : round(total / config.SUMO_AREA_M2,  6),
    }


def scenario_name(cars: int, ped: int, bike: int, moto: int) -> str:
    """Return a filesystem-safe scenario identifier string."""
    return f"p{ped}_c{bike}_m{moto}_v{cars}"


def generate_scenario(
    cars: int,
    ped: int,
    bike: int,
    moto: int,
    scenario_dir: str | os.PathLike,
    net_file: str  = config.NET_FILE,
    poly_file: str = config.POLY_FILE,
    step_length: float = config.STEP_LENGTH,
) -> tuple:
    """Generate SUMO route + config files inside *scenario_dir*.

    Returns
    -------
    (rou_path, cfg_path) – absolute Path objects
    """
    scenario_dir = Path(scenario_dir)
    scenario_dir.mkdir(parents=True, exist_ok=True)

    name       = scenario_name(cars, ped, bike, moto)
    rou_path   = scenario_dir / f"{name}.rou.xml"
    cfg_path   = scenario_dir / f"{name}.sumocfg"

    _write_rou_xml(rou_path, cars, ped, bike, moto)
    _write_sumocfg(cfg_path, rou_path, net_file, poly_file, step_length)

    return rou_path, cfg_path


# ---------------------------------------------------------------------------
# Private XML generation helpers
# ---------------------------------------------------------------------------

def _distribute(total: int, n_flows: int) -> list:
    """Distribute *total* evenly across *n_flows*, returning a list of ints."""
    if n_flows <= 0 or total <= 0:
        return [0] * max(n_flows, 1)
    base      = total // n_flows
    remainder = total  % n_flows
    return [base + (1 if i < remainder else 0) for i in range(n_flows)]


def _ped_per_flow(total_ped: int) -> list:
    """Return a list of 12 per-flow pedestrian counts using empirical 2:3:1 weighting."""
    counts = []
    allocated = 0
    for _, routes, weight in _PED_GROUPS:
        n_routes   = len(routes)
        group_total = round(total_ped * weight * n_routes / _PED_TOTAL_WEIGHT)
        per_flow   = _distribute(group_total, n_routes)
        counts.extend(per_flow)
        allocated += group_total
    # Absorb any rounding difference into the last flow
    diff = total_ped - allocated
    counts[-1] = max(0, counts[-1] + diff)
    return counts


def _write_rou_xml(path: Path, cars: int, ped: int, bike: int, moto: int):
    """Write a SUMO route file for the specified participant counts."""

    n_bike_flows = 8 if bike > 80 else 4
    n_moto_flows = 4

    bike_per_flow  = _distribute(bike,  n_bike_flows)
    moto_per_flow  = _distribute(moto,  n_moto_flows)
    car_per_flow   = _distribute(cars,  config.CAR_FLOWS)
    ped_per_flow   = _ped_per_flow(ped)

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('')
    lines.append('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
    lines.append('        xsi:noNamespaceSchemaLocation='
                 '"http://sumo.dlr.de/xsd/routes_file.xsd">')
    lines.append('')

    # --- vType definitions ---------------------------------------------------
    lines.append('    <!-- Vehicle type definitions -->')
    lines.append('    <vType id="car" accel="0.8" decel="4.5" sigma="1.0" length="4"'
                 ' minGap="2.5" maxSpeed="13.89" guiShape="passenger"/>')
    lines.append('')
    lines.append('    <vTypeDistribution id="pedestrian">')
    lines.append('        <vType vClass="pedestrian" id="slowpedestrian"  maxSpeed="1.0"'
                 ' latAlignment="compact" probability=".33"/>')
    lines.append('        <vType vClass="pedestrian" id="avgpedestrian"   maxSpeed="1.5"'
                 ' latAlignment="compact" probability=".33"/>')
    lines.append('        <vType vClass="pedestrian" id="fastpedestrian"  maxSpeed="2.0"'
                 ' latAlignment="compact" probability=".33"/>')
    lines.append('    </vTypeDistribution>')
    lines.append('')
    lines.append('    <vTypeDistribution id="bicycle">')
    lines.append('        <vType vClass="bicycle" id="slowbicycle" maxSpeed="4.2"'
                 ' minGap="0.5" latAlignment="compact" probability=".33"/>')
    lines.append('        <vType vClass="bicycle" id="avgbicycle"  maxSpeed="5.5"'
                 ' minGap="0.5" latAlignment="compact" probability=".33"/>')
    lines.append('        <vType vClass="bicycle" id="fastbicycle" maxSpeed="6.9"'
                 ' minGap="0.5" latAlignment="compact" probability=".33"/>')
    lines.append('    </vTypeDistribution>')
    lines.append('')
    lines.append('    <vTypeDistribution id="ptw">')
    lines.append('        <vType vClass="motorcycle" id="motorcycle" personCapacity="2"'
                 ' latAlignment="arbitrary" lcPushy="1.0" minGapLat="0.5" minGap="0.5"'
                 ' probability=".70" tau="1" speedDev="0.1"/>')
    lines.append('        <vType vClass="moped"      id="moped"      personCapacity="1"'
                 ' latAlignment="arbitrary" lcPushy="1.0" minGapLat="0.5" minGap="0.5"'
                 ' probability=".30" tau="1" speedDev="0.1"/>')
    lines.append('    </vTypeDistribution>')
    lines.append('')

    # --- Route definitions ---------------------------------------------------
    lines.append('    <!-- Route definitions -->')
    for r_id, edges in _ROUTE_DEFS:
        lines.append(f'    <route id="{r_id}" edges="{edges}"/>')
    lines.append('')
    lines.append('    <routeDistribution id="routedist1">')
    for r_id, edges, prob in _ROUTE_DIST_ENTRIES:
        lines.append(f'        <route id="{r_id}" edges="{edges}" probability="{prob}"/>')
    lines.append('    </routeDistribution>')
    lines.append('')

    # --- Car flows -----------------------------------------------------------
    if cars > 0:
        lines.append('    <!-- Car flows -->')
        for i, n in enumerate(car_per_flow, start=1):
            lines.append(
                f'    <flow id="car_flow{i}" type="car" route="routedist1"'
                f' begin="0" number="{n}" period="exp(0.5)" departPos="random"/>'
            )
        lines.append('')

    # --- Bicycle flows -------------------------------------------------------
    if bike > 0:
        lines.append('    <!-- Bicycle flows -->')
        for i, n in enumerate(bike_per_flow, start=1):
            lines.append(
                f'    <flow id="bike_flow{i}" type="bicycle" route="routedist1"'
                f' begin="0" number="{n}" period="exp(10)" departPos="random"/>'
            )
        lines.append('')

    # --- Motorcycle / PTW flows ----------------------------------------------
    if moto > 0:
        lines.append('    <!-- Motorcycle (PTW) flows -->')
        for i, n in enumerate(moto_per_flow, start=1):
            lines.append(
                f'    <flow id="moto_flow{i}" type="ptw" route="routedist1"'
                f' begin="0" number="{n}" period="exp(10)" departPos="random"/>'
            )
        lines.append('')

    # --- Pedestrian personFlows ----------------------------------------------
    if ped > 0:
        lines.append('    <!-- Pedestrian personFlows -->')
        all_routes = [r for _, routes, _ in _PED_GROUPS for r in routes]
        for i, (r_id, n_ped) in enumerate(zip(all_routes, ped_per_flow)):
            lines.append(
                f'    <personFlow id="pf_{i}" begin="{config.PERSONFLOW_BEGIN_S:.2f}"'
                f' number="{n_ped}" period="exp(10)" departPos="random">'
            )
            lines.append(f'        <walk route="{r_id}"/>')
            lines.append('    </personFlow>')
        lines.append('')

    lines.append('</routes>')
    lines.append('')

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_sumocfg(
    cfg_path: Path,
    rou_path: Path,
    net_file: str,
    poly_file: str,
    step_length: float = config.STEP_LENGTH,
):
    """Write a minimal SUMO configuration file."""
    # Use relative or absolute paths depending on whether net_file is absolute.
    # We store paths relative to the project root; SUMO resolves them relative
    # to the sumocfg location.  Compute relative net/poly paths from cfg_path.
    project_root = Path(__file__).parent
    abs_net   = (project_root / net_file).resolve()
    abs_poly  = (project_root / poly_file).resolve()
    abs_rou   = rou_path.resolve()
    cfg_dir   = cfg_path.parent.resolve()

    rel_net   = os.path.relpath(abs_net,  cfg_dir)
    rel_poly  = os.path.relpath(abs_poly, cfg_dir)
    rel_rou   = os.path.relpath(abs_rou,  cfg_dir)

    content = (
        "<configuration>\n"
        "    <input>\n"
        f'        <net-file value="{rel_net}"/>\n'
        f'        <route-files value="{rel_rou}"/>\n'
        f'        <additional-files value="{rel_poly}"/>\n'
        "    </input>\n"
        f'    <processing>\n'
        f'        <step-length value="{step_length}"/>\n'
        "    </processing>\n"
        "</configuration>\n"
    )
    cfg_path.write_text(content, encoding="utf-8")
