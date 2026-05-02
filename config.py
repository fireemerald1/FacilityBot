# ─── Role IDs ────────────────────────────────────────────────────────
ROLE_OWNER              = 1495417053363044372
ROLE_SUPERVISOR_TESTER  = 1495416585647554775
ROLE_SUPERVISOR_GATHERER = 1495416922223935528
ROLE_SUPERVISOR_BUILDER = 1495416737057738752
ROLE_TESTER             = 1495414585040044166
ROLE_GATHERER           = 1495416252154384384
ROLE_BUILDER            = 1495416107819995246

# ─── Channel IDs ─────────────────────────────────────────────────────
CHANNEL_TESTER    = 1495426390584070224
CHANNEL_BUILDER   = 1495426422863302777
CHANNEL_GATHERER  = 1495426446230028449
CHANNEL_ALERT     = 1495427216966680686
CHANNEL_PROMOTION = 1495426979736977501
CHANNEL_GENERAL_STAFF = 1495371969070104659
CHANNEL_MEDIA         = 1495413696288264343

# ─── Constants ───────────────────────────────────────────────────────
MAX_ACTIVE_EMBEDS   = 2          # Max concurrent active embeds per system
CODE_LENGTH         = 10         # Length of generated codes
SLOT_CHAR_LIMIT     = 50         # Max chars per test-chamber slot
TRAP_CODE           = "&^^^&"    # The trap code sequence
TRAP_CHANCE         = 0.10       # 10% chance to generate trap code
MUTATION_CHANCE     = 0.10       # 10% chance to mutate a char in tester
GATHERER_INTERVAL_H = 3          # Hours between gatherer embeds
BUILDER_CHECK_INTERVAL_S = 30    # Seconds between builder top-up checks
TESTER_CHECK_INTERVAL_S  = 30    # Seconds between tester top-up checks

# ─── Storage ─────────────────────────────────────────────────────────
import os as _os
_DATA_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data")
_os.makedirs(_DATA_DIR, exist_ok=True)

CHAMBER_FILE = _os.path.join(_DATA_DIR, "test-chamber.json")
SCHEDULE_FILE = _os.path.join(_DATA_DIR, "schedule-state.json")

# ─── Schedule ────────────────────────────────────────────────────────
ACTIVE_DAYS = {5, 6}               # Saturday=5, Sunday=6 (weekday())
ACTIVE_START_HOUR = 5              # 05:00 UTC
ACTIVE_END_HOUR   = 17             # 17:00 UTC
LATE_THRESHOLD_MINUTES = 5         # Minutes after 05:00 to count as "late"
SCHEDULE_CHECK_INTERVAL_S = 30     # How often the scheduler loop ticks

OUTAGE_MESSAGES = [
    "The remains have been processed. Production is stable.",
    "Excess material has been cleared from the system. Operations continue.",
    "Chamber congestion has been resolved. Testing continues.",
    "Resource flow has been restored after temporary blockage.",
    "All cycles have been concluded. A new cycle has started.",
    "Material accumulation has been reduced. Systems are stable.",
    "The interruption was caused by processing delay. Execution continues.",
    "System flow was obstructed. Pathways are now clear.",
    "Residual data has been cleared. Operations continue.",
    "The system has corrected an internal imbalance. Stability confirmed.",
    "Systems have resumed after a temporary interruption.",
    "Operations have continued after a brief pause.",
    "The system has returned to normal function.",
    "A temporary halt has ended. Processes continue.",
    "Activity has resumed following routine downtime.",
    "The system is active again. Operations continue.",
    "A short interruption has passed. Execution continues.",
    "Systems have re-entered normal operation.",
    "The process has resumed after interruption.",
    "All functions are active following downtime."
]
