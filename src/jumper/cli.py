"""Command line interface.

    python -m jumper board
    python -m jumper plan plan.json
    python -m jumper plan plan.json --json
    python -m jumper plan plan.json --quiet     # exit 1 if there are errors

The JSON plan format is::

    {
      "name": "Weather station",
      "wifi": true,
      "devices": [
        {"name": "BME280", "logic": "3.3V", "has_pullups": true,
         "connectors": [{"name": "SDA", "signal": "I2C_SDA"},
                        {"name": "SCL", "signal": "I2C_SCL"}],
         "pins": {"SDA": "D21", "SCL": "D22"}}
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .board import DEVKIT_V1, Board
from .errors import JumperError
from .model import Connector, Device, Direction, LogicLevel, Signal
from .plan import WiringPlan
from .render import plan_to_json, render_board, render_diagnostics, render_plan
from .diagnostics import Severity

__all__ = ["build_parser", "load_plan", "main"]


def _device_from_dict(payload: dict[str, Any]) -> Device:
    name = payload["name"]
    logic = LogicLevel(payload.get("logic", "3.3V"))
    connectors = tuple(
        Connector(
            name=entry["name"],
            signal=Signal[entry["signal"]],
            direction=Direction(entry["direction"]) if entry.get("direction") else None,
        )
        for entry in payload.get("connectors", [])
    )
    pins: dict[str, str] = payload.get("pins", {})
    if not connectors and pins:
        raise ValueError(f"device {name!r} has pins but no connectors")
    return Device(
        name=name,
        logic=logic,
        connectors=connectors,
        needs_power=payload.get("needs_power", True),
        needs_ground=payload.get("needs_ground", True),
        has_pullups=payload.get("has_pullups", False),
    )


def load_plan(path: Path, board: Board = DEVKIT_V1) -> WiringPlan:
    """Build a plan from a JSON description."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    plan = WiringPlan(
        payload.get("name", path.stem),
        board=board,
        wifi=bool(payload.get("wifi", False)),
        description=payload.get("description", ""),
    )
    for entry in payload.get("devices", []):
        device = _device_from_dict(entry)
        plan.add_device(device, auto_power=entry.get("auto_power", True))
        for connector, pin in entry.get("pins", {}).items():
            plan.wire(device.name, connector, pin)
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jumper",
        description="Validate and document ESP32 DevKit V1 wiring plans.",
    )
    parser.add_argument("--version", action="version", version=f"jumper {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    board_cmd = sub.add_parser("board", help="print the pinout of the board")
    board_cmd.add_argument("--json", action="store_true", help="emit JSON instead of a table")

    plan_cmd = sub.add_parser("plan", help="validate a JSON wiring plan")
    plan_cmd.add_argument("path", type=Path, help="path to the plan JSON file")
    plan_cmd.add_argument("--json", action="store_true", help="emit the resolved plan as JSON")
    plan_cmd.add_argument("--quiet", action="store_true", help="print nothing; fail on errors")

    return parser


def _board_json(board: Board) -> str:
    return json.dumps(
        {
            "name": board.name,
            "reserved": board.reserved,
            "pins": [
                {
                    "label": pin.label,
                    "gpio": pin.gpio,
                    "side": pin.side.value,
                    "capabilities": str(pin.capabilities).split(),
                    "aliases": list(pin.aliases),
                }
                for pin in board
            ],
        },
        indent=2,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = build_parser().parse_args(argv)

    try:
        if args.command == "board":
            print(_board_json(DEVKIT_V1) if args.json else render_board(DEVKIT_V1))
            return 0

        plan = load_plan(args.path)
        if args.json:
            print(plan_to_json(plan))
        elif not args.quiet:
            print(render_plan(plan))
        return 1 if plan.errors() else 0
    except FileNotFoundError:
        print(f"error: no such file: {args.path}", file=sys.stderr)
        return 2
    except (JumperError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
