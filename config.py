"""
config.py
~~~~~~~~~
Central configuration for VRU Urban Traffic Generator.
All simulation constants, defaults, and network parameters are defined here.
"""

# ---------------------------------------------------------------------------
# Network / area constants
# ---------------------------------------------------------------------------
SUMO_AREA_KM2 = 0.25          # km² – ETSI TR 138.913 urban scenario network footprint
SUMO_AREA_M2  = SUMO_AREA_KM2 * 1_000_000  # = 250 000 m²

# ---------------------------------------------------------------------------
# Car limits  (road saturation empirically derived from V6-V19 density scenarios)
# ---------------------------------------------------------------------------
MAX_CARS       = 120           # hard cap – more than this causes SUMO to stall/jam
CAR_FLOWS      = 8             # number of car <flow> entries in the route file
CARS_PER_FLOW  = MAX_CARS // CAR_FLOWS    # = 15 vehicles per flow

# ---------------------------------------------------------------------------
# Default VRU split when auto-proposing a distribution
# (fractions must sum to 1.0; motorcycles default to 5 % of VRU)
# ---------------------------------------------------------------------------
DEFAULT_VRU_SPLIT = {
    "pedestrian"  : 0.70,
    "bicycle"     : 0.25,
    "motorcycle"  : 0.05,
}

# ---------------------------------------------------------------------------
# Simulation timing
# All agent flows are injected within FLOW_INJECT_WINDOW_S seconds (t=0 to
# t=15 s) using per-flow computed periods, so the warm-up only needs to cover
# the injection window plus a short stabilisation period.
# Result: warmup 30 s (was 220 s) – an ~86 % reduction in simulation overhead.
# ---------------------------------------------------------------------------
STEP_LENGTH            = 0.001    # 1 ms per simulation step (all V0-V19 scenarios)
DEFAULT_WARMUP_S       = 30       # seconds: 15 s inject + 15 s stabilise (was 220 s)
DEFAULT_SAMPLING_S     = 50       # seconds (configurable by user)

DEFAULT_WARMUP_STEPS   = int(DEFAULT_WARMUP_S   / STEP_LENGTH)   # 30 000
DEFAULT_SAMPLING_STEPS = int(DEFAULT_SAMPLING_S / STEP_LENGTH)   # 50 000

# All flow and personFlow elements use begin=0, end=FLOW_INJECT_WINDOW_S.
# The per-flow period is computed as FLOW_INJECT_WINDOW_S / n_vehicles so
# every agent enters within this window regardless of quantity.
FLOW_INJECT_WINDOW_S = 15.0   # seconds

# PersonFlow injection begins at this simulation time (seconds).
# Set to 0 so pedestrians enter alongside vehicles (no artificial delay).
PERSONFLOW_BEGIN_S = 0.0

# ---------------------------------------------------------------------------
# SUMO asset paths  (relative to project root)
# ---------------------------------------------------------------------------
NET_FILE  = "sumo_assets/V3_ETSI_TR_138_913_V14_3_0_urban.net.xml"
POLY_FILE = "sumo_assets/ETSI_TR_138_913_V14_3_0_urban.poly.xml"

# ---------------------------------------------------------------------------
# Output directories
# ---------------------------------------------------------------------------
SCENARIOS_DIR = "scenarios"     # generated .rou.xml / .sumocfg and output CSVs live here
