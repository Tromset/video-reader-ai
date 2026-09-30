"""Timestamp parsing shared by the CLI and navigation reports."""

from __future__ import annotations

import math
import re


def parse_timestamp(value: str) -> float:
    """Accept seconds, MM:SS or HH:MM:SS, with up to millisecond precision."""
    value = value.strip()
    if not re.fullmatch(r"\d+(?::\d{2}){0,2}(?:\.\d{1,3})?", value):
        raise ValueError("utilisez des secondes, MM:SS ou HH:MM:SS (ex. 83.5 ou 01:23.500)")
    parts = value.split(":")
    if any(float(part) >= 60 for part in parts[1:]):
        raise ValueError("les secondes et minutes après ':' doivent être inférieures à 60")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    if not math.isfinite(seconds):
        raise ValueError("le timestamp doit être fini")
    return seconds


def format_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    whole, fraction = divmod(milliseconds, 1000)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    stamp = f"{minutes:02d}:{secs:02d}"
    if hours:
        stamp = f"{hours:02d}:{stamp}"
    return f"{stamp}.{fraction:03d}" if fraction else stamp
