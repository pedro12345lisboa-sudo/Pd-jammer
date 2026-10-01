"""Validation rules of the wiring plan."""

from __future__ import annotations

import unittest

from jumper import (
    DEVKIT_V1,
    Connector,
    Device,
    DuplicateDeviceError,
    LogicLevel,
    Rule,
    Severity,
    Signal,
    UnknownConnectorError,
    UnknownPinError,
    WiringInvalidError,
    WiringPlan,
)


def rules_of(plan: WiringPlan) -> set[Rule]:
    return {finding.rule for finding in plan.validate()}


def findings_for(plan: WiringPlan, rule: Rule) -> list:
    return [finding for finding in plan.validate() if finding.rule is rule]


def i2c_device(name: str = "BME280", **kwargs) -> Device:
    return Device(
        name,
        connectors=(
            Connector("SDA", Signal.I2C_SDA),
            Connector("SCL", Signal.I2C_SCL),
        ),
        **kwargs,
    )


class HappyPathTest(unittest.TestCase):
    def test_default_i2c_layout_is_valid(self) -> None:
        plan = WiringPlan("Weather station")
        plan.add_device(i2c_device(has_pullups=True))
        plan.wire("BME280", "SDA", "D21")
        plan.wire("BME280", "SCL", "D22")

        self.assertTrue(plan.is_valid)
        self.assertEqual(plan.errors(), ())
        plan.assert_valid()

    def test_power_and_ground_are_created_automatically(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device(has_pullups=True))
        kinds = sorted(wire.signal.value for wire in plan.connections)
        self.assertEqual(kinds, ["3V3", "GND"])

        plan.wire("BME280", "SDA", "D21")
        plan.wire("BME280", "SCL", "D22")
        kinds = sorted(wire.signal.value for wire in plan.connections)
        self.assertEqual(kinds, ["3V3", "GND", "I2C_SCL", "I2C_SDA"])

    def test_five_v_peripheral_uses_the_vin_rail(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(Device("RELAY", logic=LogicLevel.FIVE_V, connectors=(Connector("IN", Signal.GPIO_IN),)))
        supply = next(wire for wire in plan.connections if wire.is_power)
        self.assertEqual(supply.pin.label, "VIN")

    def test_validate_is_deterministic(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device())
        plan.wire("BME280", "SDA", "D34")
        first = [str(finding) for finding in plan.validate()]
        second = [str(finding) for finding in plan.validate()]
        self.assertEqual(first, second)

    def test_free_labels_skip_used_and_input_only_pins(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device(has_pullups=True))
        plan.wire("BME280", "SDA", "D21")
        plan.wire("BME280", "SCL", "D22")
        free = plan.free_labels()
        self.assertNotIn("D21", free)
        self.assertNotIn("D34", free)
        self.assertIn("D25", free)

    def test_input_only_pins_can_be_asked_for_explicitly(self) -> None:
        plan = WiringPlan("p")
        self.assertIn("D34", plan.free_labels(include_input_only=True))


class ProgrammingErrorTest(unittest.TestCase):
    def test_unknown_pin_raises_with_suggestion(self) -> None:
        plan = WiringPlan("p")
        with self.assertRaises(UnknownPinError):
            plan.connect("D99", Signal.GPIO_OUT, "X", "Y")

    def test_unknown_connector_raises(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device())
        with self.assertRaises(UnknownConnectorError):
            plan.wire("BME280", "SDA_WRONG", "D21")

    def test_wiring_an_undeclared_device_raises(self) -> None:
        plan = WiringPlan("p")
        with self.assertRaises(UnknownConnectorError):
            plan.wire("ghost", "SDA", "D21")

    def test_duplicate_device_raises(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device())
        with self.assertRaises(DuplicateDeviceError):
            plan.add_device(i2c_device())

    def test_unknown_signal_name_is_reported_clearly(self) -> None:
        plan = WiringPlan("p")
        with self.assertRaises(ValueError) as ctx:
            plan.add_wire_device("X", pins=[("a", "D2", "NOT_A_SIGNAL")])
        self.assertIn("NOT_A_SIGNAL", str(ctx.exception))


class RuleTest(unittest.TestCase):
    def test_output_on_input_only_pin_is_an_error(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device(
            "LATCH",
            pins=[("data", "D34", "GPIO_OUT")],
            needs_power=True,
            needs_ground=True,
        )
        findings = findings_for(plan, Rule.PIN_INPUT_ONLY)
        self.assertEqual(len(findings), 1)
        self.assertIs(findings[0].severity, Severity.ERROR)
        self.assertIn("D34", findings[0].message)

    def test_reading_an_input_only_pin_is_fine(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device(
            "LDR",
            pins=[("wiper", "D34", "ADC_READ")],
            needs_power=True,
            needs_ground=True,
        )
        self.assertEqual(findings_for(plan, Rule.PIN_INPUT_ONLY), [])

    def test_ground_on_a_gpio_is_an_error(self) -> None:
        plan = WiringPlan("p")
        plan.connect("D21", Signal.GROUND, "MODULE", "GND")
        self.assertIn(Rule.PIN_INPUT_ONLY, rules_of(plan))

    def test_power_on_a_gpio_is_an_error(self) -> None:
        plan = WiringPlan("p")
        plan.connect("D21", Signal.POWER_3V3, "MODULE", "VCC")
        self.assertIn(Rule.PIN_INPUT_ONLY, rules_of(plan))

    def test_reusing_a_pin_is_an_error(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device(has_pullups=True))
        plan.wire("BME280", "SDA", "D21")
        plan.wire("BME280", "SCL", "D21")
        findings = findings_for(plan, Rule.PIN_ALREADY_USED)
        self.assertEqual(len(findings), 1)
        self.assertIs(findings[0].severity, Severity.ERROR)

    def test_several_ground_jumpers_are_only_a_warning(self) -> None:
        plan = WiringPlan("p")
        plan.connect("GND", Signal.GROUND, "A", "GND")
        plan.connect("GND", Signal.GROUND, "B", "GND")
        findings = findings_for(plan, Rule.GROUND_DUPLICATED)
        self.assertEqual(len(findings), 1)
        self.assertIs(findings[0].severity, Severity.WARNING)

    def test_strapping_pin_is_flagged_with_an_explanation(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device("SPI", pins=[("CS", "D5", "SPI_CS")], needs_power=False, needs_ground=True)
        findings = findings_for(plan, Rule.PIN_STRAPPING)
        self.assertEqual(len(findings), 1)
        self.assertIs(findings[0].severity, Severity.WARNING)
        self.assertIn("HIGH at reset", findings[0].hint)

    def test_uart0_conflict_is_flagged(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device("GPS", pins=[("TX", "TX0", "UART_TX")], needs_power=False, needs_ground=True)
        self.assertIn(Rule.PIN_UART0, rules_of(plan))

    def test_uart2_is_not_flagged(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device("GPS", pins=[("TX", "TX2", "UART_TX")], needs_power=False, needs_ground=True)
        self.assertNotIn(Rule.PIN_UART0, rules_of(plan))

    def test_adc2_with_wifi_is_an_error(self) -> None:
        plan = WiringPlan("p", wifi=True)
        plan.add_wire_device(
            "POT",
            pins=[("wiper", "D25", "ADC_READ")],
            needs_power=False,
            needs_ground=True,
        )
        findings = findings_for(plan, Rule.ADC2_WITH_WIFI)
        self.assertEqual(len(findings), 1)
        self.assertIs(findings[0].severity, Severity.ERROR)

    def test_adc2_without_wifi_is_fine(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device(
            "POT",
            pins=[("wiper", "D25", "ADC_READ")],
            needs_power=False,
            needs_ground=True,
        )
        self.assertNotIn(Rule.ADC2_WITH_WIFI, rules_of(plan))

    def test_adc1_with_wifi_is_fine(self) -> None:
        plan = WiringPlan("p", wifi=True)
        plan.add_wire_device(
            "POT",
            pins=[("wiper", "D32", "ADC_READ")],
            needs_power=False,
            needs_ground=True,
        )
        self.assertNotIn(Rule.ADC2_WITH_WIFI, rules_of(plan))

    def test_missing_ground_is_an_error(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device(has_pullups=True), auto_power=False)
        plan.wire("BME280", "SDA", "D21")
        plan.wire("BME280", "SCL", "D22")
        self.assertIn(Rule.POWER_MISSING, rules_of(plan))
        self.assertIn(Rule.GROUND_MISSING, rules_of(plan))

    def test_three_v_three_peripheral_on_the_five_v_rail_is_an_error(self) -> None:
        plan = WiringPlan("p")
        plan.connect("VIN", Signal.POWER_3V3, "MODULE", "VCC")
        self.assertIn(Rule.POWER_CONFLICT, rules_of(plan))

    def test_five_v_into_a_three_v_three_pin_is_an_error(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device(
            "HC-SR04",
            pins=[("echo", "D34", "SENSOR_IN")],
            logic=LogicLevel.FIVE_V,
            connectors=(
                Connector("echo", Signal.SENSOR_IN, voltage=LogicLevel.FIVE_V),
            ),
        )
        findings = findings_for(plan, Rule.LEVEL_MISMATCH)
        self.assertTrue(findings)
        self.assertIs(findings[0].severity, Severity.ERROR)
        self.assertIn("divider", findings[0].hint)

    def test_three_v_three_into_a_five_v_peripheral_is_a_warning(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device(
            "HC-SR04",
            pins=[("trig", "TX2", "TRIGGER_OUT")],
            logic=LogicLevel.FIVE_V,
        )
        findings = findings_for(plan, Rule.LEVEL_MARGIN)
        self.assertEqual(len(findings), 1)
        self.assertIs(findings[0].severity, Severity.WARNING)
        self.assertIn("VIH", findings[0].hint)

    def test_declaring_the_contact_as_three_v_three_clears_the_warning(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device(
            "HC-SR04",
            pins=[("trig", "TX2", "TRIGGER_OUT")],
            logic=LogicLevel.FIVE_V,
            connectors=(Connector("trig", Signal.TRIGGER_OUT, voltage=LogicLevel.THREE_V3),),
        )
        self.assertNotIn(Rule.LEVEL_MARGIN, rules_of(plan))
        self.assertTrue(plan.is_valid)

    def test_internal_pullups_are_suggested_for_open_drain_buses(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device())
        plan.wire("BME280", "SDA", "D21")
        plan.wire("BME280", "SCL", "D22")
        findings = findings_for(plan, Rule.INTERNAL_I2C)
        self.assertEqual(len(findings), 2)
        self.assertIs(findings[0].severity, Severity.INFO)

    def test_declared_pullups_silence_the_suggestion(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device(has_pullups=True))
        plan.wire("BME280", "SDA", "D21")
        plan.wire("BME280", "SCL", "D22")
        self.assertNotIn(Rule.INTERNAL_I2C, rules_of(plan))

    def test_unused_declared_connector_is_informational(self) -> None:
        plan = WiringPlan("p")
        plan.add_device(i2c_device(has_pullups=True))
        plan.wire("BME280", "SDA", "D21")
        findings = findings_for(plan, Rule.CONNECTOR_UNUSED)
        self.assertEqual(len(findings), 1)
        self.assertIn("SCL", findings[0].message)
        self.assertIs(findings[0].severity, Severity.INFO)

    def test_button_on_input_only_pin_warns_about_the_missing_pullup(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device(
            "BUTTON",
            pins=[("leg", "D35", "BUTTON_IN")],
            needs_power=False,
            needs_ground=True,
        )
        findings = findings_for(plan, Rule.NO_INTERNAL_PULLUP)
        self.assertEqual(len(findings), 1)
        self.assertIn("10000", findings[0].hint)

    def test_assert_valid_raises_on_errors(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device("X", pins=[("a", "D34", "GPIO_OUT")], needs_power=True, needs_ground=True)
        with self.assertRaises(WiringInvalidError) as ctx:
            plan.assert_valid()
        self.assertIn("input-only", str(ctx.exception))


class ReportOrderTest(unittest.TestCase):
    def test_errors_are_reported_before_warnings(self) -> None:
        plan = WiringPlan("p")
        plan.add_wire_device("X", pins=[("a", "D34", "GPIO_OUT"), ("b", "D5", "GPIO_OUT")])
        severities = [finding.severity.rank for finding in plan.validate()]
        self.assertEqual(severities, sorted(severities, reverse=True))


if __name__ == "__main__":
    unittest.main()
