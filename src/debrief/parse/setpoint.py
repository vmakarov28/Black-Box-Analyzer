"""Setpoint reconstruction, matching Plasmatree PID-Analyzer's method exactly.

Betaflight's P-term is computed as::

    axisP[axis] = P_gain * PTERM_SCALE * (setpoint - gyro)

with the internal scaling constant ``PTERM_SCALE = 0.032029``. Solving for
the setpoint the flight controller actually targeted::

    setpoint = gyro + axisP[axis] / (PTERM_SCALE * P_gain)

This is preferred over reconstructing setpoint from rcCommand + the rates
curve because it needs no rates-formula bookkeeping (which differs across
Betaflight rates types and versions) and it reflects what the PID loop
itself saw, including RC smoothing/interpolation and feedforward-adjacent
shaping already baked into axisP by the firmware.

Constant and derivation cross-checked against
vendor/PID-Analyzer/PID-Analyzer.py:Trace.pid_in (not shipped in this repo;
see docs/phase1-parser-evaluation.md for how to fetch it for validation).
"""
from __future__ import annotations

import numpy as np

PTERM_SCALE = 0.032029

_AXES = ("roll", "pitch", "yaw")


def reconstruct_setpoint(gyro: np.ndarray, axis_p_term: np.ndarray, p_gain: float | None) -> np.ndarray:
    """setpoint = gyro + P_term / (PTERM_SCALE * p_gain); NaN array if p_gain is unknown/zero."""
    if not p_gain:
        return np.full_like(gyro, np.nan, dtype=np.float64)
    return gyro + axis_p_term / (PTERM_SCALE * p_gain)


def add_setpoint_columns(df, pid_gains: dict) -> list[str]:
    """Add setpoint_roll/pitch/yaw columns to *df* in place (deg/s).

    Returns the list of axis names that were successfully reconstructed
    (missing P gain or missing axisP/gyroADC columns leaves that axis out
    rather than fabricating a value).
    """
    done = []
    for i, axis in enumerate(_AXES):
        gyro_col = f"gyroADC[{i}]"
        p_col = f"axisP[{i}]"
        gains = pid_gains.get(axis)
        if gyro_col not in df.columns or p_col not in df.columns or gains is None or gains.P is None:
            continue
        df[f"setpoint_{axis}"] = reconstruct_setpoint(
            df[gyro_col].to_numpy(dtype=np.float64), df[p_col].to_numpy(dtype=np.float64), gains.P
        )
        done.append(axis)
    return done
