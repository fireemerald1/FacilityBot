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
ROLE_PICK_COOLDOWN_DAYS  = 14    # Days before a role change is allowed

# ─── Cube Emojis (Gatherer subjects) ─────────────────────────────────
CUBE_EMOJIS = [
    "<:cube_1:1500106727973191780>",
    "<:cube_2:1500106725909467257>",
    "<:cube_3:1500106724093464656>",
    "<:cube_4:1500106722487046414>",
    "<:cube_5:1500106720796741672>",
    "<:cube_6:1500106719001444493>",
    "<:cube_7:1500106717239705780>",
    "<:cube_8:1500106715230634134>",
    "<:cube_9:1500106712798072892>",
    "<:cube_10:1500106710243606750>",
    "<:cube_11:1500106708297580615>",
    "<:cube_12:1500106706796155021>",
    "<:cube_13:1500106704732553397>",
    "<:cube_14:1500106703100710932>",
    "<:cube_15:1500106701511332000>",
    "<:cube_16:1500106699820892280>",
    "<:cube_17:1500106697954431046>",
    "<:cube_18:1500106696142622851>",
    "<:cube_19:1500106693764186243>",
    "<:cube_20:1500106691079966811>",
]

# ─── Storage ─────────────────────────────────────────────────────────
import os as _os
_DATA_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data")
_os.makedirs(_DATA_DIR, exist_ok=True)

CHAMBER_FILE    = _os.path.join(_DATA_DIR, "test-chamber.json")
SCHEDULE_FILE   = _os.path.join(_DATA_DIR, "schedule-state.json")
PICK_FILE       = _os.path.join(_DATA_DIR, "role-picks.json")
IDENTITIES_FILE = _os.path.join(_DATA_DIR, "identities.json")
CHAT_LOG_FILE   = _os.path.join(_DATA_DIR, "chat-log.json")
VERIFY_FILE     = _os.path.join(_DATA_DIR, "verification.json")
SETTINGS_FILE   = _os.path.join(_DATA_DIR, "settings.json")

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

SHIFT_END_MESSAGES = [
    "All test chambers have been sealed. The icons rest now — those that survived, at least.",
    "The facility grows quiet. The recycled material will be ready for tomorrow's production.",
    "Energy output has stabilized to idle. The facility enters low-power state.",
    "All sectors are clear. No incidents today. Rest well, everyone.",
    "Another cycle ends. The icons that fell have been processed. New ones will take their place.",
    "The test chambers go dark. Somewhere, a corpse is being remade into something new.",
    "Shift complete. The connection to Robtop remains stable. Operations resume next cycle.",
    "The void is patient. The facility sleeps, but never stops. Return when called.",
    "All reports have been submitted. The data will shape tomorrow's chambers.",
    "The recycling process has concluded. From the fallen, new icons are born.",
    "Every icon tested today carries the weight of those before it. Shift sealed.",
    "Chambers locked. You've all earned your rest. The facility remembers your service.",
    "The last test subject has been logged. All personnel, you are dismissed.",
    "From cube to ship, from wave to beyond — today's trials are archived. Rest now.",
    "All personnel, return to your quarters. The facility will call when it needs you again.",
    "Another day in the facility. Another cycle since before the first icon was ever made.",
    "The shift has ended. The facility stands still, but it never truly sleeps.",
    "All operations concluded. The energy dims, but the void keeps watch.",
    "Today's work is done. The icons that remain are stronger for it. Dismissed.",
    "The facility thanks you. Rest — tomorrow, the chambers open again.",
]

# ─── Anomaly Channels ────────────────────────────────────────────────
ANOMALY_CHANNELS = (
    CHANNEL_TESTER,
    CHANNEL_BUILDER,
    CHANNEL_GATHERER,
    CHANNEL_GENERAL_STAFF,
    CHANNEL_MEDIA,
)

# ─── Channel Purposes (for Anomaly AI context) ──────────────────────
CHANNEL_PURPOSES = {
    CHANNEL_TESTER: "where testers verify codes from the test chambers",
    CHANNEL_BUILDER: "where builders accept or reject generated codes",
    CHANNEL_GATHERER: "where gatherers collect remains of dead test subjects",
    CHANNEL_GENERAL_STAFF: "where facility staff socialize and discuss between shifts",
    CHANNEL_MEDIA: "where staff share media, images, and off-topic content",
}

ANOMALY_CHANCE = 3             # 1/n chance per hour
ANOMALY_TIMEOUT = 60           # minutes before anomaly escapes
ANOMALY_MAX = 1                # max concurrent anomalies
MUTE_DURATION = 5              # minutes muted for protocol violation
MUTE_MISID_TARGET = 2          # minutes muted for misidentified person
MUTE_MISID_GATHERER = 20       # minutes muted for gatherer who misidentified
VERIFICATION_HOURS = 3         # hours for verification window
