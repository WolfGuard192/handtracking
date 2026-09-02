# config.py
"""
Default configuration parameters for the HandClose project.
Adjust these values as needed.
"""

# Hand state transition
MAX_TRANSITION_TIME = 1.5  # seconds allowed between OPEN -> FIST
COOLDOWN = 10.0  # seconds cooldown after a trigger

# Mediapipe / detection
HAND_CONFIDENCE = 0.7  # min detection confidence
TRACKING_CONFIDENCE = 0.6

# Graceful close behavior
GRACE_PERIOD = 4.0  # seconds to wait after WM_CLOSE before force kill

# Logging
LOG_DIR = "logs"
LOG_FILE = f"{LOG_DIR}/handclose.log"

# Defaults
DEFAULT_WHITELIST = [
    "explorer.exe",
    "System",
    "wininit.exe",
    "services.exe",
    "svchost.exe",
]
