"""jumper - wiring plans for the ESP32 DevKit V1.

Describe the board and the peripherals, let the library work out which jumpers
exist, and get a table plus a list of wiring mistakes back.

    >>> from jumper import DEVKIT_V1, WiringPlan
    >>> plan = WiringPlan("Blink", board=DEVKIT_V1)
    >>> plan.add_wire_device(
    ...     "LED",
    ...     pins=[("anode", "D2", "GPIO_OUT")],
    ...     needs_power=False,
    ...     needs_ground=True,
    ... )
    WiringPlan(name='Blink', board='ESP32 DevKit V1 (30-pin)', devices=1, jumpers=2, wifi=False)
    >>> plan.is_valid
    True
    >>> [wire.label for wire in plan.connections]
    ['LED.GND', 'LED.anode']
"""

from __future__ import annotations

from .board import DEVKIT_V1, Board, Pin
from .diagnostics import Diagnostic, Rule, Severity
from .errors import (
    DuplicateDeviceError,
    JumperError,
    UnknownConnectorError,
    UnknownPinError,
    WiringInvalidError,
)
from .model import Capability, Connector, Device, Direction, LogicLevel, Signal, Side
from .plan import Connection, WiringPlan
from .render import (
    plan_to_dict,
    plan_to_json,
    render_board,
    render_diagnostics,
    render_plan,
)

__version__ = "1.0.0"

__all__ = [
    "Board",
    "Capability",
    "Connection",
    "Connector",
    "DEVKIT_V1",
    "Device",
    "Diagnostic",
    "Direction",
    "DuplicateDeviceError",
    "JumperError",
    "LogicLevel",
    "Pin",
    "Rule",
    "Severity",
    "Side",
    "Signal",
    "UnknownConnectorError",
    "UnknownPinError",
    "WiringInvalidError",
    "WiringPlan",
    "__version__",
    "plan_to_dict",
    "plan_to_json",
    "render_board",
    "render_diagnostics",
    "render_plan",
]
