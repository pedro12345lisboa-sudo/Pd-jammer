"""Board table integrity and lookup behaviour."""

from __future__ import annotations

import unittest

from jumper import DEVKIT_V1, Board, Capability, LogicLevel, Pin, Side, Signal, UnknownPinError
from jumper.model import Direction


class BoardTableTest(unittest.TestCase):
    def test_header_has_thirty_contacts(self) -> None:
        self.assertEqual(len(DEVKIT_V1), 30)

    def test_sides_are_balanced(self) -> None:
        self.assertEqual(len(DEVKIT_V1.side(Side.LEFT)), 13)
        self.assertEqual(len(DEVKIT_V1.side(Side.RIGHT)), 13)
        self.assertEqual(len(DEVKIT_V1.side(Side.POWER)), 4)

    def test_two_ground_contacts_and_both_rails_exist(self) -> None:
        self.assertEqual(len(DEVKIT_V1.ground_labels), 2)
        self.assertEqual(DEVKIT_V1.rails, (("VIN", LogicLevel.FIVE_V), ("3V3", LogicLevel.THREE_V3)))

    def test_lookup_is_case_insensitive_and_accepts_aliases(self) -> None:
        self.assertEqual(DEVKIT_V1.lookup("d21").gpio, 21)
        self.assertEqual(DEVKIT_V1.lookup("SDA").gpio, 21)
        self.assertEqual(DEVKIT_V1.lookup("scl").gpio, 22)
        self.assertEqual(DEVKIT_V1.lookup("5V").label, "VIN")

    def test_lookup_suggests_a_close_match(self) -> None:
        with self.assertRaises(UnknownPinError) as ctx:
            DEVKIT_V1.lookup("D2O")
        suggestion = ctx.exception.suggestion
        self.assertIsNotNone(suggestion)
        self.assertEqual(DEVKIT_V1.lookup(suggestion).label, suggestion)

    def test_unknown_pin_has_no_suggestion_when_far(self) -> None:
        with self.assertRaises(UnknownPinError) as ctx:
            DEVKIT_V1.lookup("banana")
        self.assertIsNone(ctx.exception.suggestion)

    def test_find_returns_none_instead_of_raising(self) -> None:
        self.assertIsNone(DEVKIT_V1.find("banana"))

    def test_gpio_numbers_are_unique(self) -> None:
        numbers = [pin.gpio for pin in DEVKIT_V1 if pin.gpio is not None]
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_input_only_pins(self) -> None:
        expected = {"VP", "VN", "D34", "D35"}
        actual = {pin.label for pin in DEVKIT_V1 if pin.is_input_only}
        self.assertEqual(actual, expected)

    def test_strapping_pins(self) -> None:
        actual = {pin.gpio for pin in DEVKIT_V1 if pin.is_strapping}
        self.assertEqual(actual, {2, 5, 12, 15})

    def test_psram_conflict_is_flagged_on_gpio15(self) -> None:
        self.assertTrue(DEVKIT_V1.lookup("D15").capabilities & Capability.PSRAM)

    def test_reserved_gpio0_is_documented(self) -> None:
        self.assertIn("GPIO0", DEVKIT_V1.reserved)
        self.assertIsNone(DEVKIT_V1.by_gpio(0))

    def test_input_only_pins_have_no_internal_pullup(self) -> None:
        for pin in DEVKIT_V1:
            if pin.is_input_only:
                self.assertFalse(pin.has_internal_pullup, pin.label)

    def test_power_rails_support_only_power_and_ground(self) -> None:
        self.assertTrue(DEVKIT_V1.rail(LogicLevel.THREE_V3).supports(Direction.SUPPLY))
        self.assertFalse(DEVKIT_V1.rail(LogicLevel.THREE_V3).supports(Direction.OUTPUT))
        self.assertTrue(DEVKIT_V1.rail(LogicLevel.THREE_V3, ground=True).supports(Direction.RETURN))

    def test_default_i2c_bus_pins_are_usable(self) -> None:
        for label in ("D21", "D22"):
            self.assertTrue(DEVKIT_V1.lookup(label).capabilities & Capability.I2C)

    def test_adc1_and_adc2_split_matches_datasheet(self) -> None:
        adc1 = {pin.gpio for pin in DEVKIT_V1 if pin.capabilities & Capability.ADC1}
        adc2 = {pin.gpio for pin in DEVKIT_V1 if pin.capabilities & Capability.ADC2}
        self.assertEqual(adc1, {32, 33, 34, 35, 36, 39})
        self.assertEqual(adc2, {2, 4, 12, 13, 14, 15, 25, 26, 27})

    def test_every_output_capable_pin_can_also_be_read(self) -> None:
        for pin in DEVKIT_V1:
            if pin.capabilities & Capability.OUTPUT:
                self.assertTrue(pin.capabilities & Capability.INPUT, pin.label)

    def test_only_input_only_pins_lack_an_output_driver(self) -> None:
        without_output = {pin.label for pin in DEVKIT_V1 if pin.gpio is not None and not (pin.capabilities & Capability.OUTPUT)}
        self.assertEqual(without_output, {"VP", "VN", "D34", "D35"})


class BoardConstructionTest(unittest.TestCase):
    def test_duplicate_gpio_is_rejected(self) -> None:
        pins = (
            Pin("A", 4, Side.LEFT, Capability.INPUT | Capability.OUTPUT),
            Pin("B", 4, Side.RIGHT, Capability.INPUT | Capability.OUTPUT),
        )
        with self.assertRaises(ValueError):
            Board("broken", pins)

    def test_duplicate_label_is_rejected(self) -> None:
        pins = (
            Pin("A", 4, Side.LEFT, Capability.INPUT | Capability.OUTPUT),
            Pin("A", 5, Side.RIGHT, Capability.INPUT | Capability.OUTPUT),
        )
        with self.assertRaises(ValueError):
            Board("broken", pins)

    def test_contradictory_capabilities_are_rejected(self) -> None:
        pins = (Pin("A", 4, Side.LEFT, Capability.OUTPUT | Capability.INPUT_ONLY),)
        with self.assertRaises(ValueError):
            Board("broken", pins)


if __name__ == "__main__":
    unittest.main()
