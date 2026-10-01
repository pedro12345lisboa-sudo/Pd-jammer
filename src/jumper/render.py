"""Rendering: fixed-width tables for terminals and JSON for tooling."""

from __future__ import annotations

import json
from typing import Any, Iterable

from .diagnostics import Diagnostic, Severity, count_by_severity
from .model import Capability
from .plan import WiringPlan

__all__ = ["render_board", "render_plan", "render_diagnostics", "plan_to_dict", "plan_to_json"]

_SEVERITY_GLYPH = {"info": "i", "warning": "!", "error": "x"}


def _table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    header_list = [str(h) for h in headers]
    body = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
    widths = [len(h) for h in header_list]
    for row in body:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(header_list)).rstrip()]
    lines.append("  ".join("-" * width for width in widths).rstrip())
    for row in body:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def render_plan(plan: WiringPlan, *, show_diagnostics: bool = True) -> str:
    """Human-readable wiring table plus the validation summary."""
    sections: list[str] = [f"{plan.name}  ({plan.board.name}, wifi={'on' if plan.wifi else 'off'})"]
    if plan.description:
        sections.append(plan.description)
    if not plan.connections:
        sections.append("(no jumpers)")
        return "\n".join(sections)

    sections.append("")
    sections.append(
        _table(
            ("pin", "gpio", "side", "signal", "to", "dir", "note"),
            (
                (
                    wire.pin.label,
                    wire.pin.gpio if wire.pin.gpio is not None else "-",
                    wire.pin.side.value,
                    wire.signal.value,
                    wire.label,
                    wire.direction.value,
                    wire.note,
                )
                for wire in plan.connections
            ),
        )
    )

    free = plan.free_labels()
    sections.append("")
    sections.append(f"free GPIOs: {', '.join(free) if free else 'none'}")

    if show_diagnostics:
        findings = plan.validate()
        sections.append("")
        sections.append(render_diagnostics(findings))
    return "\n".join(sections)


def render_diagnostics(findings: Iterable[Diagnostic]) -> str:
    """One block per finding, grouped by severity."""
    items = list(findings)
    if not items:
        return "validation: ok, no findings"

    counts = count_by_severity(items)
    summary = ", ".join(f"{counts[sev]} {sev.value}" for sev in Severity if counts[sev])
    lines = [f"validation: {len(items)} finding(s) [{summary}]"]
    for item in items:
        where = " ".join(
            part
            for part in (
                f"pin={item.pin}" if item.pin else "",
                f"device={item.device}" if item.device else "",
                f"connector={item.connector}" if item.connector else "",
            )
            if part
        )
        glyph = _SEVERITY_GLYPH[item.severity.value]
        lines.append(f"  {glyph} {item.rule.value:30} {item.message}" + (f"  ({where})" if where else ""))
        if item.hint:
            lines.append(f"      hint: {item.hint}")
    return "\n".join(lines)


def render_board(board) -> str:
    """Full pinout of a board, with warnings first."""
    def flags(pin) -> str:
        notes: list[str] = []
        if pin.is_input_only:
            notes.append("input-only")
        if pin.is_strapping:
            notes.append("strapping")
        if pin.capabilities & Capability.PSRAM:
            notes.append("psram")
        return ", ".join(notes)

    rows = (
        (
            pin.label,
            pin.gpio if pin.gpio is not None else "-",
            pin.side.value,
            _capability_text(pin.capabilities),
            flags(pin),
        )
        for pin in board
    )
    return _table(("pin", "gpio", "side", "capabilities", "notes"), rows)


def _capability_text(capabilities) -> str:
    interesting = ("INPUT", "OUTPUT", "PULLUP", "PULLDOWN", "ADC1", "ADC2", "DAC", "PWM", "TOUCH", "SPI", "I2C", "UART", "FLASH")
    present = [name for name in interesting if capabilities & getattr(Capability, name)]
    return " ".join(name.lower() for name in present) if present else "-"


def plan_to_dict(plan: WiringPlan) -> dict[str, Any]:
    """JSON-friendly representation of the plan and its findings."""
    return {
        "name": plan.name,
        "board": plan.board.name,
        "description": plan.description,
        "wifi": plan.wifi,
        "devices": [
            {
                "name": device.name,
                "logic": device.logic.value,
                "connectors": [
                    {"name": c.name, "signal": c.signal.value, "direction": c.resolved_direction.value}
                    for c in device.connectors
                ],
                "has_pullups": device.has_pullups,
            }
            for device in plan.devices
        ],
        "connections": [
            {
                "pin": wire.pin.label,
                "gpio": wire.pin.gpio,
                "side": wire.pin.side.value,
                "signal": wire.signal.value,
                "device": wire.device,
                "connector": wire.connector,
                "direction": wire.direction.value,
                "note": wire.note,
            }
            for wire in plan.connections
        ],
        "diagnostics": [
            {
                "severity": d.severity.value,
                "rule": d.rule.value,
                "message": d.message,
                "pin": d.pin,
                "device": d.device,
                "connector": d.connector,
                "hint": d.hint,
            }
            for d in plan.validate()
        ],
    }


def plan_to_json(plan: WiringPlan, *, indent: int = 2) -> str:
    return json.dumps(plan_to_dict(plan), indent=indent, sort_keys=False)
