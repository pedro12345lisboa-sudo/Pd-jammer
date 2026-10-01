"""Exception hierarchy.

Only *programmer* errors raise: unknown pins, unknown connectors, duplicate
devices. Everything that can be fixed by rewiring is reported as a
:class:`~jumper.diagnostics.Diagnostic` instead, so a plan can be validated
as a whole before touching hardware.
"""

from __future__ import annotations

from typing import Iterable, Optional

__all__ = [
    "JumperError",
    "UnknownPinError",
    "UnknownConnectorError",
    "DuplicateDeviceError",
    "WiringInvalidError",
]


class JumperError(Exception):
    """Base class for every error raised by this library."""


class UnknownPinError(JumperError, KeyError):
    """Raised when a board label cannot be resolved."""

    def __init__(self, label: str, suggestion: Optional[str] = None) -> None:
        self.label = label
        self.suggestion = suggestion
        hint = f"; did you mean {suggestion!r}?" if suggestion else ""
        KeyError.__init__(self, f"unknown pin {label!r}{hint}")
        self.message = f"unknown pin {label!r}{hint}"

    def __str__(self) -> str:
        return self.message


class UnknownConnectorError(JumperError, KeyError):
    """Raised when a peripheral connector cannot be resolved."""

    def __init__(self, device: str, connector: str, available: Iterable[str]) -> None:
        self.device = device
        self.connector = connector
        options = ", ".join(available) or "<none>"
        self.message = f"device {device!r} has no connector {connector!r}; available: {options}"
        KeyError.__init__(self, self.message)

    def __str__(self) -> str:
        return self.message


class DuplicateDeviceError(JumperError, ValueError):
    """Raised when the same peripheral name is registered twice."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.message = f"device {name!r} is already registered"
        ValueError.__init__(self, self.message)

    def __str__(self) -> str:
        return self.message


class WiringInvalidError(JumperError):
    """Raised by :meth:`WiringPlan.assert_valid` when errors are present."""

    def __init__(self, diagnostics: Iterable[object]) -> None:
        self.diagnostics = tuple(diagnostics)
        detail = "\n".join(f"  [{d.severity.value}] {d.rule.value}: {d.message}" for d in self.diagnostics)
        self.message = f"wiring plan is invalid:\n{detail}" if detail else "wiring plan is invalid"
        super().__init__(self.message)
