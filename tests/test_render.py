"""Reporting: tables, JSON export and the command line interface."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jumper import (
    Connector,
    Device,
    LogicLevel,
    Signal,
    WiringPlan,
    __version__,
    cli,
    plan_to_dict,
    plan_to_json,
    render_board,
    render_diagnostics,
    render_plan,
)
from jumper.board import DEVKIT_V1

PLAN_JSON = {
    "name": "Weather station",
    "description": "BME280 over I2C plus a status LED",
    "wifi": True,
    "devices": [
        {
            "name": "BME280",
            "logic": "3.3V",
            "has_pullups": True,
            "connectors": [
                {"name": "SDA", "signal": "I2C_SDA"},
                {"name": "SCL", "signal": "I2C_SCL"},
            ],
            "pins": {"SDA": "D21", "SCL": "D22"},
        },
        {
            "name": "LED",
            "connectors": [{"name": "anode", "signal": "GPIO_OUT"}],
            "pins": {"anode": "D23"},
        },
    ],
}


def build_plan() -> WiringPlan:
    plan = WiringPlan("Weather station", description="BME280 over I2C", wifi=True)
    plan.add_device(Device("BME280", connectors=(Connector("SDA", Signal.I2C_SDA), Connector("SCL", Signal.I2C_SCL)), has_pullups=True))
    plan.wire("BME280", "SDA", "D21")
    plan.wire("BME280", "SCL", "D22")
    return plan


class RenderTest(unittest.TestCase):
    def test_table_lists_every_jumper(self) -> None:
        text = render_plan(build_plan())
        self.assertIn("Weather station", text)
        for expected in ("D21", "BME280.SDA", "GND", "3V3", "free GPIOs", "validation:"):
            self.assertIn(expected, text)

    def test_empty_plan_renders_without_crashing(self) -> None:
        text = render_plan(WiringPlan("empty"))
        self.assertIn("(no jumpers)", text)

    def test_board_table_marks_dangerous_pins(self) -> None:
        text = render_board(DEVKIT_V1)
        self.assertIn("input-only", text)
        self.assertIn("strapping", text)
        self.assertIn("psram", text)

    def test_diagnostics_render_is_readable(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device("X", pins=[("a", "D34", "GPIO_OUT")])
        text = render_diagnostics(plan.validate())
        self.assertIn("pin/input-only", text)
        self.assertIn("hint:", text)

    def test_no_findings_renders_as_ok(self) -> None:
        self.assertIn("ok", render_diagnostics(build_plan().validate()))


class JsonTest(unittest.TestCase):
    def test_round_trip_is_valid_json_with_expected_shape(self) -> None:
        payload = plan_to_dict(build_plan())
        self.assertEqual(payload["board"], DEVKIT_V1.name)
        self.assertTrue(payload["wifi"])
        self.assertEqual(len(payload["connections"]), 4)
        self.assertEqual(payload["devices"][0]["name"], "BME280")
        json.loads(plan_to_json(build_plan()))

    def test_json_includes_diagnostics(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device("X", pins=[("a", "D34", "GPIO_OUT")])
        self.assertTrue(plan_to_dict(plan)["diagnostics"])


class CliTest(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(argv)
        return code, buffer.getvalue()

    def test_board_command_succeeds(self) -> None:
        code, output = self._run(["board"])
        self.assertEqual(code, 0)
        self.assertIn("D21", output)

    def test_board_command_json(self) -> None:
        code, output = self._run(["board", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(output)["pins"]), 30)

    def test_plan_command_returns_zero_when_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(json.dumps(PLAN_JSON), encoding="utf-8")
            code, output = self._run(["plan", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("BME280.SCL", output)

    def test_plan_command_returns_one_when_invalid(self) -> None:
        payload = json.loads(json.dumps(PLAN_JSON))
        payload["devices"][0]["pins"]["SDA"] = "D34"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, _ = self._run(["plan", str(path), "--quiet"])
        self.assertEqual(code, 1)

    def test_missing_file_reports_a_clean_error(self) -> None:
        code, _ = self._run(["plan", "/nonexistent/plan.json"])
        self.assertEqual(code, 2)

    def test_bad_pin_reports_a_clean_error(self) -> None:
        payload = json.loads(json.dumps(PLAN_JSON))
        payload["devices"][0]["pins"]["SDA"] = "D99"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, _ = self._run(["plan", str(path), "--quiet"])
        self.assertEqual(code, 2)

    def test_version_flag(self) -> None:
        with self.assertRaises(SystemExit):
            cli.main(["--version"])
        self.assertTrue(__version__)


class DocstringTest(unittest.TestCase):
    def test_package_examples_still_work(self) -> None:
        import doctest

        import jumper

        results = doctest.testmod(jumper, verbose=False)
        self.assertEqual(results.failed, 0)


if __name__ == "__main__":
    unittest.main()
