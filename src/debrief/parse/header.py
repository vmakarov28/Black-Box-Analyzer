"""Betaflight/Cleanflight blackbox header parsing.

A blackbox log's header is a run of plain-text ``H key:value`` lines at the
start of each embedded flight. Parsing it needs no external decoder at all --
we read it straight out of the raw file bytes.

Two views are exposed, deliberately kept separate:

* ``raw``    -- the verbatim ``{key: value}`` strings exactly as logged.
  This is the ONLY thing Phase 6 (tune generator) is allowed to read from,
  because its whitelist/version-guard round-trip check must prove a key
  literally exists in the source config -- a normalized/aliased view could
  silently paper over a firmware-version mismatch.
* ``HeaderConfig`` -- a best-effort normalized view for the DSP/rules/report
  layers, built from an alias table covering the Cleanflight/BF3.x legacy PID
  format through modern (BF4.3+) split-key/simplified-tuning format. Fields
  we can't confidently locate are left ``None`` rather than guessed -- see
  the TUNABLE markers below for the specific spots that are best-effort.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADER_BLOCK_MARKER = b"H Product:"


def find_header_offsets(raw: bytes) -> list[int]:
    """Byte offset of each embedded log's header block, in file order."""
    return [m.start() for m in re.finditer(re.escape(HEADER_BLOCK_MARKER), raw)]


def parse_header_block(raw: bytes, start: int) -> dict[str, str]:
    """Parse one contiguous run of ``H key:value`` lines starting at *start*."""
    header: dict[str, str] = {}
    pos = start
    n = len(raw)
    while pos < n:
        nl = raw.find(b"\n", pos)
        if nl == -1:
            nl = n
        line = raw[pos:nl]
        if line.endswith(b"\r"):
            line = line[:-1]
        if not line.startswith(b"H "):
            break
        text = line[2:].decode("latin-1")
        key, sep, value = text.partition(":")
        if sep:
            header[key.strip()] = value.strip()
        pos = nl + 1
    return header


@dataclass
class AxisGains:
    P: float | None = None
    I: float | None = None
    D: float | None = None
    F: float | None = None


@dataclass
class HeaderConfig:
    """Best-effort normalized view of a raw header dict. Always carries the
    raw dict alongside it -- consult ``raw`` for anything safety-critical.
    """

    raw: dict[str, str]
    firmware_type: str | None = None
    firmware_name: str | None = None            # "Betaflight" / "Cleanflight" / "KISS" / "Raceflight"
    firmware_version: tuple[int, int, int] | None = None
    target: str | None = None
    craft_name: str | None = None
    looptime_us: float | None = None
    gyro_rate_hz: float | None = None
    pid_loop_rate_hz: float | None = None
    pid_gains: dict[str, AxisGains] = field(default_factory=dict)  # roll/pitch/yaw
    rates_raw: dict[str, str] = field(default_factory=dict)
    gyro_lowpass_hz: float | None = None
    gyro_lowpass2_hz: float | None = None
    dterm_lowpass_hz: float | None = None
    dterm_lowpass2_hz: float | None = None
    gyro_notch_hz: list[float] = field(default_factory=list)
    gyro_notch_cutoff: list[float] = field(default_factory=list)
    dterm_notch_hz: float | None = None
    dterm_notch_cutoff: float | None = None
    dyn_notch_enabled: bool | None = None
    dyn_notch_min_hz: float | None = None
    dyn_notch_max_hz: float | None = None
    dyn_notch_count: int | None = None
    dyn_notch_q: float | None = None
    rpm_filter_enabled: bool | None = None
    rpm_filter_harmonics: int | None = None
    motor_poles: int | None = None
    dshot_bidir: bool | None = None
    motor_protocol: str | None = None
    dyn_idle_min_rpm: float | None = None
    tpa_rate: float | None = None
    tpa_breakpoint: float | None = None
    anti_gravity_gain: float | None = None
    simplified_tuning_active: bool = False
    debug_mode: str | None = None
    features: int | None = None


# ---------------------------------------------------------------------------
# alias tables: canonical field -> raw header keys to try, in priority order.
# Covers Cleanflight/BF3.x legacy keys and BF4.x split-key format observed in
# the wild. Not guaranteed exhaustive across every firmware fork/version --
# unmatched fields are left None rather than guessed (see module docstring).
# ---------------------------------------------------------------------------
_SIMPLE_ALIASES: dict[str, tuple[str, ...]] = {
    "firmware_type": ("Firmware type",),
    "craft_name": ("Craft name",),
    "looptime_us": ("looptime",),
    "gyro_sync_denom": ("gyro_sync_denom",),
    "pid_process_denom": ("pid_process_denom",),
    "gyro_lowpass_hz": ("gyro_lowpass_hz", "gyro_lpf_hz", "gyro_lowpass_hz_ex", "gyro_lowpass"),
    "gyro_lowpass2_hz": ("gyro_lowpass2_hz",),
    "dterm_lowpass_hz": ("dterm_lpf_hz", "dterm_lowpass_hz"),
    "dterm_lowpass2_hz": ("dterm_lowpass2_hz",),
    "dterm_notch_hz": ("dterm_notch_hz",),
    "dterm_notch_cutoff": ("dterm_notch_cutoff",),
    "dyn_notch_min_hz": ("dyn_notch_min_hz",),
    "dyn_notch_max_hz": ("dyn_notch_max_hz",),
    "dyn_notch_count": ("dyn_notch_count",),
    "dyn_notch_q": ("dyn_notch_q",),
    "rpm_filter_harmonics": ("rpm_filter_harmonics",),
    "motor_poles": ("motor_poles",),
    "dyn_idle_min_rpm": ("dyn_idle_min_rpm", "dynamic_idle_min_rpm"),
    "tpa_rate": ("tpa_rate", "dynThrPID"),
    "tpa_breakpoint": ("tpa_breakpoint",),
    "anti_gravity_gain": ("anti_gravity_gain", "anti_gravity_gain_ff", "anti_gravity_gain_p"),
    "debug_mode": ("debug_mode",),
    "features": ("features",),
    "motor_protocol": ("motor_pwm_protocol", "fast_pwm_protocol"),
}

_AXIS_LEGACY_KEYS = {"roll": "rollPID", "pitch": "pitchPID", "yaw": "yawPID"}
_AXIS_SPLIT_PREFIX = {"roll": "roll", "pitch": "pitch", "yaw": "yaw"}


def _to_float(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _to_int(v: str | None) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


def _first(raw: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        if k in raw:
            return raw[k]
    return None


def _parse_pid_gains(raw: dict[str, str]) -> dict[str, AxisGains]:
    gains: dict[str, AxisGains] = {}
    for axis, legacy_key in _AXIS_LEGACY_KEYS.items():
        if legacy_key in raw:
            # legacy Cleanflight/BF3.x comma format: "P,I,D"
            parts = raw[legacy_key].split(",")
            vals = [_to_float(p) for p in parts]
            vals += [None] * (4 - len(vals))
            gains[axis] = AxisGains(P=vals[0], I=vals[1], D=vals[2], F=vals[3])
            continue
        prefix = _AXIS_SPLIT_PREFIX[axis]
        p = raw.get(f"p_{prefix}")
        i = raw.get(f"i_{prefix}")
        d = raw.get(f"d_{prefix}")
        f = raw.get(f"f_{prefix}")
        if p is not None or i is not None or d is not None:
            gains[axis] = AxisGains(P=_to_float(p), I=_to_float(i), D=_to_float(d), F=_to_float(f))
    return gains


def _parse_notches(raw: dict[str, str]) -> tuple[list[float], list[float]]:
    hz = raw.get("gyro_notch_hz", "")
    cut = raw.get("gyro_notch_cutoff", "")
    hz_list = [v for v in (_to_float(x) for x in hz.split(",") if x != "") if v]
    cut_list = [v for v in (_to_float(x) for x in cut.split(",") if x != "") if v]
    return hz_list, cut_list


def _parse_firmware(raw: dict[str, str]) -> tuple[str | None, tuple[int, int, int] | None, str | None]:
    rev = raw.get("Firmware revision", "")
    m = re.match(r"(\S+)\s+(\d+)\.(\d+)\.(\d+)\s*(?:\(([0-9a-f]+)\))?\s*(\S+)?", rev)
    if not m:
        return (rev or None, None, None)
    name = m.group(1)
    version = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
    target = m.group(6)
    return name, version, target


def normalize(raw: dict[str, str]) -> HeaderConfig:
    cfg = HeaderConfig(raw=raw)
    cfg.firmware_type = raw.get("Firmware type")
    cfg.firmware_name, cfg.firmware_version, cfg.target = _parse_firmware(raw)
    cfg.craft_name = raw.get("Craft name")

    cfg.looptime_us = _to_float(_first(raw, _SIMPLE_ALIASES["looptime_us"]))
    gyro_denom = _to_float(raw.get("gyro_sync_denom")) or 1.0
    pid_denom = _to_float(raw.get("pid_process_denom")) or 1.0
    if cfg.looptime_us:
        cfg.gyro_rate_hz = 1e6 / cfg.looptime_us
        cfg.pid_loop_rate_hz = cfg.gyro_rate_hz / pid_denom if pid_denom else cfg.gyro_rate_hz
    # gyro_denom is informational for very old FW where looptime already
    # reflects gyro rate; not applied to avoid double-counting (TUNABLE:
    # revisit if we see a log where this materially disagrees).
    del gyro_denom

    cfg.pid_gains = _parse_pid_gains(raw)

    for rk in ("rcRate", "rcExpo", "rcYawRate", "rcYawExpo", "rates_type",
               "roll_rc_rate", "pitch_rc_rate", "yaw_rc_rate",
               "roll_expo", "pitch_expo", "yaw_expo",
               "roll_srate", "pitch_srate", "yaw_srate", "rates"):
        if rk in raw:
            cfg.rates_raw[rk] = raw[rk]

    cfg.gyro_lowpass_hz = _to_float(_first(raw, _SIMPLE_ALIASES["gyro_lowpass_hz"]))
    cfg.gyro_lowpass2_hz = _to_float(_first(raw, _SIMPLE_ALIASES["gyro_lowpass2_hz"]))
    cfg.dterm_lowpass_hz = _to_float(_first(raw, _SIMPLE_ALIASES["dterm_lowpass_hz"]))
    cfg.dterm_lowpass2_hz = _to_float(_first(raw, _SIMPLE_ALIASES["dterm_lowpass2_hz"]))
    cfg.dterm_notch_hz = _to_float(_first(raw, _SIMPLE_ALIASES["dterm_notch_hz"]))
    cfg.dterm_notch_cutoff = _to_float(_first(raw, _SIMPLE_ALIASES["dterm_notch_cutoff"]))
    cfg.gyro_notch_hz, cfg.gyro_notch_cutoff = _parse_notches(raw)

    cfg.dyn_notch_min_hz = _to_float(_first(raw, _SIMPLE_ALIASES["dyn_notch_min_hz"]))
    cfg.dyn_notch_max_hz = _to_float(_first(raw, _SIMPLE_ALIASES["dyn_notch_max_hz"]))
    cfg.dyn_notch_count = _to_int(_first(raw, _SIMPLE_ALIASES["dyn_notch_count"]))
    cfg.dyn_notch_q = _to_float(_first(raw, _SIMPLE_ALIASES["dyn_notch_q"]))
    if "dyn_notch_count" in raw or "dyn_notch_min_hz" in raw:
        cfg.dyn_notch_enabled = (cfg.dyn_notch_count or 0) > 0

    rpm_harm = _to_int(_first(raw, _SIMPLE_ALIASES["rpm_filter_harmonics"]))
    cfg.rpm_filter_harmonics = rpm_harm
    if rpm_harm is not None:
        cfg.rpm_filter_enabled = rpm_harm > 0
    cfg.motor_poles = _to_int(_first(raw, _SIMPLE_ALIASES["motor_poles"]))

    if "dshot_bidir" in raw:
        cfg.dshot_bidir = raw["dshot_bidir"].strip().upper() in ("ON", "1", "TRUE")
    cfg.motor_protocol = _first(raw, _SIMPLE_ALIASES["motor_protocol"])

    cfg.dyn_idle_min_rpm = _to_float(_first(raw, _SIMPLE_ALIASES["dyn_idle_min_rpm"]))
    cfg.tpa_rate = _to_float(_first(raw, _SIMPLE_ALIASES["tpa_rate"]))
    cfg.tpa_breakpoint = _to_float(_first(raw, _SIMPLE_ALIASES["tpa_breakpoint"]))
    cfg.anti_gravity_gain = _to_float(_first(raw, _SIMPLE_ALIASES["anti_gravity_gain"]))

    cfg.simplified_tuning_active = raw.get("simplified_pids_mode", "").upper() == "ON"
    cfg.debug_mode = raw.get("debug_mode")
    cfg.features = _to_int(raw.get("features"))
    return cfg
