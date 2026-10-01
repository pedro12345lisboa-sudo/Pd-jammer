"""Validation rules and their diagnostics.

A :class:`Diagnostic` is a machine-readable finding about a wiring plan.
Rules never raise: they describe how to fix the wiring, not how to call the
library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence

__all__ = ["Diagnostic", "Rule", "Severity"]


class Severity(Enum):
    """How much a finding matters."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    @property
    def rank(self) -> int:
        return {"info": 0, "warning": 1, "error": 2}[self.value]


class Rule(Enum):
    """Stable identifiers for every check, usable as CI suppression keys."""

    PIN_INPUT_ONLY = "pin/input-only"
    PIN_STRAPPING = "pin/strapping"
    PIN_UART0 = "pin/uart0"
    PIN_PSRAM = "pin/psram"
    PIN_ALREADY_USED = "pin/already-used"

    NO_INTERNAL_PULLUP = "pin/no-internal-pullup"
    ADC2_WITH_WIFI = "adc/adc2-with-wifi"

    POWER_CONFLICT = "power/multiple-sources"
    POWER_MISSING = "power/peripheral-not-powered"
    GROUND_MISSING = "power/peripheral-without-ground"
    GROUND_DUPLICATED = "power/duplicate-ground"
    POWER_RAIL_SHARED = "power/shared-rail"
    LEVEL_MISMATCH = "power/level-mismatch"
    LEVEL_MARGIN = "power/insufficient-level"

    CONNECTOR_UNUSED = "device/connector-unused"
    DEVICE_UNWIRED = "device/not-wired"
    INTERNAL_I2C = "bus/internal-pullups-absent"

    @property
    def severity(self) -> Severity:
        return _RULE_SEVERITY[self]


_RULE_SEVERITY: dict[Rule, Severity] = {
    Rule.PIN_INPUT_ONLY: Severity.ERROR,
    Rule.PIN_STRAPPING: Severity.WARNING,
    Rule.PIN_UART0: Severity.WARNING,
    Rule.PIN_PSRAM: Severity.WARNING,
    Rule.PIN_ALREADY_USED: Severity.ERROR,
    Rule.NO_INTERNAL_PULLUP: Severity.WARNING,
    Rule.ADC2_WITH_WIFI: Severity.ERROR,
    Rule.POWER_CONFLICT: Severity.ERROR,
    Rule.POWER_MISSING: Severity.ERROR,
    Rule.GROUND_MISSING: Severity.ERROR,
    Rule.GROUND_DUPLICATED: Severity.WARNING,
    Rule.POWER_RAIL_SHARED: Severity.INFO,
    Rule.LEVEL_MISMATCH: Severity.ERROR,
    Rule.LEVEL_MARGIN: Severity.WARNING,
    Rule.CONNECTOR_UNUSED: Severity.INFO,
    Rule.DEVICE_UNWIRED: Severity.INFO,
    Rule.INTERNAL_I2C: Severity.INFO,
}

_STRAPPING_NOTES = {
    0: "GPIO0 is sampled at reset: pull LOW to enter the bootloader.",
    2: "GPIO2 must be LOW or floating at reset; it drives the on-board LED.",
    5: "GPIO5 must be HIGH at reset (internal pull-up).",
    12: "GPIO12 must be LOW at reset; the internal pull-down already forces this, "
    "so an external pull-up stops the chip from booting.",
    15: "GPIO15 must be HIGH at reset (internal pull-up).",
}


@dataclass(frozen=True, slots=True, order=False)
class Diagnostic:
    """A single finding about a wiring plan."""

    severity: Severity
    rule: Rule
    message: str
    pin: Optional[str] = None
    device: Optional[str] = None
    connector: Optional[str] = None
    hint: Optional[str] = None

    def __str__(self) -> str:
        where = " ".join(
            part
            for part in (
                f"pin={self.pin}" if self.pin else "",
                f"device={self.device}" if self.device else "",
                f"connector={self.connector}" if self.connector else "",
            )
            if part
        )
        base = f"[{self.severity.value.upper():7}] {self.rule.value:32} {self.message}"
        if where:
            base = f"{base}  ({where})"
        if self.hint:
            base = f"{base}\n{'':11}{self.hint}"
        return base


def sort_diagnostics(items: Iterable[Diagnostic]) -> list[Diagnostic]:
    """Most severe first, then stable by rule and pin."""
    return sorted(items, key=lambda d: (-d.severity.rank, d.rule.value, d.pin or "", d.device or ""))


def count_by_severity(items: Sequence[Diagnostic]) -> dict[Severity, int]:
    counts = {severity: 0 for severity in Severity}
    for item in items:
        counts[item.severity] += 1
    return counts


def strapping_note(gpio: Optional[int]) -> str:
    """Human explanation for a strapping pin, when one exists."""
    if gpio is None:
        return ""
    return _STRAPPING_NOTES.get(gpio, "This pin is sampled at reset.")
