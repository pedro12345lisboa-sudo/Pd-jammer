"""Wiring plan: describe the board, then validate it.

Typical use::

    from jumper import DEVKIT_V1, Board, Device, Connector, Signal, WiringPlan

    plan = WiringPlan("Weather station", board=DEVKIT_V1)
    plan.add_device(Device(
        "BME280",
        connectors=(
            Connector("SDA", Signal.I2C_SDA),
            Connector("SCL", Signal.I2C_SCL),
        ),
    ))
    plan.wire("BME280", "SDA", "D21")
    plan.wire("BME280", "SCL", "D22")
    plan.enable_wifi()

    for issue in plan.validate():
        print(issue)
    plan.assert_valid()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .board import DEVKIT_V1, Board, Pin
from .diagnostics import Diagnostic, Rule, Severity, sort_diagnostics, strapping_note
from .errors import DuplicateDeviceError, UnknownConnectorError, UnknownPinError
from .model import Capability, Connector, Device, Direction, LogicLevel, Signal

__all__ = ["Connection", "WiringPlan"]

_CONNECTOR_POWER = ("VCC", "VIN", "+", "5V", "3V3")
_CONNECTOR_GROUND = ("GND", "-")


def _connector_power_kind(name: str) -> Optional[str]:
    key = name.strip().upper()
    if key in _CONNECTOR_GROUND:
        return "gnd"
    if key in _CONNECTOR_POWER:
        return "vcc"
    return None


@dataclass(frozen=True, slots=True)
class Connection:
    """One physical jumper wire."""

    pin: Pin
    signal: Signal
    device: str
    connector: str
    direction: Direction
    note: str = ""
    declared_voltage: Optional[LogicLevel] = None

    @property
    def is_power(self) -> bool:
        return self.direction is Direction.SUPPLY

    @property
    def is_ground(self) -> bool:
        return self.direction is Direction.RETURN

    @property
    def is_data(self) -> bool:
        return self.direction.is_data

    @property
    def voltage(self) -> Optional[LogicLevel]:
        """Logic voltage actually present on the line.

        A connector declaration wins over the signal name, because plenty of
        5 V parts accept 3.3 V logic on some contacts.
        """
        return self.declared_voltage or self.signal.voltage

    @property
    def label(self) -> str:
        return f"{self.device}.{self.connector}"


class WiringPlan:
    """A board, the peripherals on it, and the wires between them."""

    def __init__(
        self,
        name: str,
        board: Board = DEVKIT_V1,
        *,
        wifi: bool = False,
        description: str = "",
    ) -> None:
        self.name = name
        self.board = board
        self.description = description
        self._wifi = wifi
        self._devices: dict[str, Device] = {}
        self._connections: list[Connection] = []
        self._ground_cursor = 0

    def __repr__(self) -> str:
        return (
            f"WiringPlan(name={self.name!r}, board={self.board.name!r}, "
            f"devices={len(self._devices)}, jumpers={len(self._connections)}, wifi={self._wifi})"
        )

    # ------------------------------------------------------------------ build

    @property
    def wifi(self) -> bool:
        """True when WiFi (or BLE) is expected to be running on the firmware."""
        return self._wifi

    def enable_wifi(self, enabled: bool = True) -> "WiringPlan":
        self._wifi = enabled
        return self

    def add_device(self, device: Device, *, auto_power: bool = True) -> "WiringPlan":
        """Register a peripheral, optionally wiring its power and ground.

        Args:
            device: the peripheral description.
            auto_power: add ``VCC``/``GND`` jumpers to the board rails.

        Raises:
            DuplicateDeviceError: if the name is taken.
        """
        if device.name in self._devices:
            raise DuplicateDeviceError(device.name)
        self._devices[device.name] = device

        if auto_power and device.needs_power:
            rail = self.board.rail(device.logic)
            self.connect(
                rail.label,
                Signal.POWER_3V3 if device.logic is LogicLevel.THREE_V3 else Signal.POWER_5V,
                device.name,
                "VCC",
            )
        if auto_power and device.needs_ground:
            self.connect(self._next_ground_pin(), Signal.GROUND, device.name, "GND")
        return self

    def _next_ground_pin(self) -> Pin:
        """Hand out ground contacts round-robin.

        The DevKit V1 exposes two GND pins, one per edge. Filling one and
        leaving the other empty makes every daisy-chained ground wire cross the
        whole board.
        """
        contacts = self.board.ground_pins
        if not contacts:
            return self.board.rail(LogicLevel.THREE_V3, ground=True)
        index = self._ground_cursor % len(contacts)
        self._ground_cursor += 1
        return contacts[index]

    def device(self, name: str) -> Device:
        try:
            return self._devices[name]
        except KeyError:
            raise UnknownConnectorError(name, "*", ()) from None

    def connect(
        self,
        pin: str | Pin,
        signal: Signal,
        device: str,
        connector: str,
        *,
        direction: Optional[Direction] = None,
        voltage: Optional[LogicLevel] = None,
        note: str = "",
    ) -> Connection:
        """Add a jumper wire. The low-level escape hatch.

        Args:
            pin: board label, e.g. ``"D21"``, ``"3V3"``, ``"GND"``.
            signal: semantic role of the wire.
            device: peripheral name.
            connector: contact name on the peripheral.
            direction: overrides the signal default.
            voltage: overrides the logic voltage implied by ``signal``.
            note: free-form text carried to the report.

        Raises:
            UnknownPinError: when the board label does not exist.
        """
        resolved = self.board.lookup(pin) if isinstance(pin, str) else pin
        wire = Connection(
            pin=resolved,
            signal=signal,
            device=device,
            connector=connector,
            direction=direction or signal.default_direction,
            note=note,
            declared_voltage=voltage,
        )
        self._connections.append(wire)
        return wire

    def wire(
        self,
        device: str,
        connector: str,
        pin: str,
        *,
        note: str = "",
    ) -> Connection:
        """Wire a declared peripheral contact to a board pin.

        The direction comes from the connector declaration, so a declared
        ``OUTPUT`` contact on an input-only pin is caught by
        :meth:`validate`.

        Raises:
            UnknownConnectorError: unknown peripheral or contact.
            UnknownPinError: unknown board label.
        """
        declared = self._devices.get(device)
        if declared is None:
            raise UnknownConnectorError(device, connector, ())
        contact = declared.connector(connector)
        return self.connect(
            pin,
            contact.signal,
            device,
            connector,
            direction=contact.resolved_direction,
            voltage=contact.voltage,
            note=note or declared.notes,
        )

    def add_wire_device(
        self,
        name: str,
        *,
        pins: Sequence[tuple[str, str, str]],
        logic: LogicLevel = LogicLevel.THREE_V3,
        connectors: Optional[Sequence[Connector]] = None,
        needs_power: bool = True,
        needs_ground: bool = True,
        has_pullups: bool = False,
    ) -> "WiringPlan":
        """Declare a peripheral whose contacts all map to GPIOs.

        Args:
            name: peripheral name.
            pins: ``(connector, board_pin, signal_name)`` triples, where
                ``signal_name`` is the :class:`~jumper.model.Signal` member
                name, e.g. ``"I2C_SDA"``.
            logic: voltage domain.
            connectors: override the auto-derived contact declarations.
            needs_power: reserve a ``VCC`` jumper.
            needs_ground: reserve a ``GND`` jumper.
            has_pullups: the module already carries pull-ups (I2C boards).

        Raises:
            ValueError: on a malformed triple or unknown signal name.
        """
        declared: list[Connector] = list(connectors) if connectors is not None else []
        if connectors is None:
            for connector, _pin, signal_name in pins:
                try:
                    signal = Signal[signal_name]
                except KeyError:
                    valid = ", ".join(s.name for s in Signal)
                    raise ValueError(
                        f"unknown signal {signal_name!r} for device {name!r}; valid names: {valid}"
                    ) from None
                declared.append(Connector(connector, signal))
        device = Device(
            name=name,
            logic=logic,
            connectors=tuple(declared),
            needs_power=needs_power,
            needs_ground=needs_ground,
            has_pullups=has_pullups,
        )
        self.add_device(device)
        for connector, board_pin, _signal_name in pins:
            self.wire(name, connector, board_pin)
        return self

    # ------------------------------------------------------------------ query

    @property
    def devices(self) -> tuple[Device, ...]:
        return tuple(self._devices.values())

    @property
    def connections(self) -> tuple[Connection, ...]:
        return tuple(self._connections)

    def used_labels(self) -> set[str]:
        return {wire.pin.label for wire in self._connections}

    def free_labels(
        self,
        capabilities: Optional[Capability] = None,
        *,
        include_input_only: bool = False,
    ) -> tuple[str, ...]:
        """Labels still free, optionally filtered by required capabilities.

        Power rails and input-only contacts are excluded by default: the former
        are shared by every peripheral, the latter cannot drive a load.
        """
        used = self.used_labels()
        labels: list[str] = []
        for pin in self.board:
            if pin.label in used or pin.gpio is None:
                continue
            if not include_input_only and pin.is_input_only:
                continue
            if capabilities is not None and pin.capabilities & capabilities != capabilities:
                continue
            labels.append(pin.label)
        return tuple(labels)

    # --------------------------------------------------------------- validate

    def validate(self) -> tuple[Diagnostic, ...]:
        """Run every rule and return the findings, most severe first.

        The result is deterministic and free of side effects, so it is safe to
        call repeatedly and to feed into CI.
        """
        findings: list[Diagnostic] = []
        findings += self._check_pin_capabilities()
        findings += self._check_single_use()
        findings += self._check_ground_and_power()
        findings += self._check_levels()
        findings += self._check_analog()
        findings += self._check_coverage()
        return tuple(sort_diagnostics(findings))

    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.validate() if d.severity is Severity.ERROR)

    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.validate() if d.severity is Severity.WARNING)

    def assert_valid(self) -> "WiringPlan":
        """Raise :class:`~jumper.errors.WiringInvalidError` if any error exists."""
        errors = self.errors()
        if errors:
            from .errors import WiringInvalidError

            raise WiringInvalidError(errors)
        return self

    @property
    def is_valid(self) -> bool:
        return not self.errors()

    # ------------------------------------------------------------------ rules

    def _check_pin_capabilities(self) -> list[Diagnostic]:
        findings: list[Diagnostic] = []
        for wire in self._connections:
            pin = wire.pin
            if not pin.supports(wire.direction):
                if wire.direction is Direction.OUTPUT and pin.is_input_only:
                    findings.append(
                        Diagnostic(
                            Severity.ERROR,
                            Rule.PIN_INPUT_ONLY,
                            f"{pin.label} is input-only and cannot be driven by the MCU",
                            pin=pin.label,
                            device=wire.device,
                            connector=wire.connector,
                            hint="GPIO34/35/36/39 have no output driver; pick another pin.",
                        )
                    )
                elif wire.direction is Direction.SUPPLY and not pin.is_power:
                    findings.append(
                        Diagnostic(
                            Severity.ERROR,
                            Rule.PIN_INPUT_ONLY,
                            f"{pin.label} is a GPIO, not a power rail",
                            pin=pin.label,
                            device=wire.device,
                            connector=wire.connector,
                            hint="Use 3V3 for 3.3 V or VIN for 5 V.",
                        )
                    )
                elif wire.direction is Direction.RETURN and not pin.is_ground:
                    findings.append(
                        Diagnostic(
                            Severity.ERROR,
                            Rule.PIN_INPUT_ONLY,
                            f"{pin.label} is a GPIO, not a ground rail",
                            pin=pin.label,
                            device=wire.device,
                            connector=wire.connector,
                            hint="Ground jumpers must land on GND.",
                        )
                    )
                elif wire.direction is Direction.BIDIRECTIONAL and not (
                    pin.capabilities & Capability.OUTPUT
                ):
                    findings.append(
                        Diagnostic(
                            Severity.ERROR,
                            Rule.PIN_INPUT_ONLY,
                            f"{pin.label} has no output driver, so it cannot take part in "
                            "an open-drain line",
                            pin=pin.label,
                            device=wire.device,
                            connector=wire.connector,
                            hint="I2C needs to pull the line low; move the bus to a regular GPIO.",
                        )
                    )
                elif wire.direction is Direction.INPUT and not (
                    pin.capabilities & Capability.INPUT
                ):
                    findings.append(
                        Diagnostic(
                            Severity.ERROR,
                            Rule.PIN_INPUT_ONLY,
                            f"{pin.label} cannot be read as {wire.direction.value}",
                            pin=pin.label,
                            device=wire.device,
                            connector=wire.connector,
                        )
                    )

            if pin.is_strapping and wire.is_data:
                findings.append(
                    Diagnostic(
                        Severity.WARNING,
                        Rule.PIN_STRAPPING,
                        f"{pin.label} is a strapping pin and is sampled at reset",
                        pin=pin.label,
                        device=wire.device,
                        connector=wire.connector,
                        hint=strapping_note(pin.gpio),
                    )
                )

            if pin.label in ("TX0", "RX0") and wire.is_data:
                findings.append(
                    Diagnostic(
                        Severity.WARNING,
                        Rule.PIN_UART0,
                        f"{pin.label} shares UART0 with the USB serial monitor",
                        pin=pin.label,
                        device=wire.device,
                        connector=wire.connector,
                        hint="Use UART2 (TX2/RX2 = GPIO17/GPIO16) for other serial devices.",
                    )
                )

            if pin.capabilities & Capability.PSRAM and wire.is_data:
                findings.append(
                    Diagnostic(
                        Severity.WARNING,
                        Rule.PIN_PSRAM,
                        f"{pin.label} is used by PSRAM on WROVER modules",
                        pin=pin.label,
                        device=wire.device,
                        connector=wire.connector,
                        hint="Keep this pin only on bare WROOM modules.",
                    )
                )
        return findings

    def _check_single_use(self) -> list[Diagnostic]:
        """One jumper per GPIO. Power and ground rails are shared by design."""
        findings: list[Diagnostic] = []

        ground_pins = self.board.ground_pins
        ground_wires = [wire for wire in self._connections if wire.is_ground]
        ground_capacity = (
            max(1, -(-len(ground_wires) // len(ground_pins))) if ground_pins else 1
        )

        by_pin: dict[int, list[Connection]] = {}
        for wire in self._connections:
            if wire.is_power:
                continue
            by_pin.setdefault(wire.pin.slot, []).append(wire)

        ground_slots = {pin.slot for pin in ground_pins}
        for slot, wires in sorted(by_pin.items()):
            if len(wires) <= 1:
                continue
            label = wires[0].pin.label
            if slot in ground_slots:
                if len(wires) > ground_capacity:
                    findings.append(
                        Diagnostic(
                            Severity.WARNING,
                            Rule.GROUND_DUPLICATED,
                            f"GND carries {len(wires)} jumpers and the board offers "
                            f"{len(ground_pins)} ground contacts",
                            pin=label,
                            hint=(
                                "Spread them over every GND pin, or feed a ground rail on the "
                                "breadboard and hang the peripherals from it."
                            ),
                        )
                    )
                continue
            endpoints = ", ".join(sorted(w.label for w in wires))
            findings.append(
                Diagnostic(
                    Severity.ERROR,
                    Rule.PIN_ALREADY_USED,
                    f"{label} is wired to {endpoints}",
                    pin=label,
                    hint="One header contact takes one jumper. Add a bus or choose another pin.",
                )
            )

        rails: dict[str, set[str]] = {}
        for wire in self._connections:
            if wire.is_power:
                rails.setdefault(wire.pin.label, set()).add(wire.device)
        for label, devices in sorted(rails.items()):
            if len(devices) > 1:
                findings.append(
                    Diagnostic(
                        Severity.INFO,
                        Rule.POWER_RAIL_SHARED,
                        f"{label} powers {len(devices)} peripherals ({', '.join(sorted(devices))})",
                        pin=label,
                        hint="Keep one jumper from the header to the breadboard rail.",
                    )
                )
        return findings

    def _check_ground_and_power(self) -> list[Diagnostic]:
        findings: list[Diagnostic] = []
        supplies: dict[str, list[Connection]] = {}
        for wire in self._connections:
            if wire.is_power:
                supplies.setdefault(wire.pin.voltage.value if wire.pin.voltage else "?", []).append(wire)

        for voltage, wires in sorted(supplies.items()):
            sources = {w.pin.label for w in wires}
            if len(sources) > 1:
                findings.append(
                    Diagnostic(
                        Severity.ERROR,
                        Rule.POWER_CONFLICT,
                        f"the {voltage} rail is fed from both {', '.join(sorted(sources))}",
                        hint="Pick one source per voltage domain.",
                    )
                )

        for wire in self._connections:
            if not wire.is_power:
                continue
            rail_level = wire.pin.voltage
            if rail_level is None or wire.signal.voltage is None:
                continue
            if rail_level is not wire.signal.voltage:
                findings.append(
                    Diagnostic(
                        Severity.ERROR,
                        Rule.POWER_CONFLICT,
                        f"{wire.label} expects {wire.signal.voltage.value} but {wire.pin.label} "
                        f"is the {rail_level.value} rail",
                        pin=wire.pin.label,
                        device=wire.device,
                        connector=wire.connector,
                        hint="3.3 V peripherals belong on 3V3, never on VIN.",
                    )
                )

        for name, device in self._devices.items():
            if device.needs_power and name not in supplies_by_device(supplies):
                findings.append(
                    Diagnostic(
                        Severity.ERROR,
                        Rule.POWER_MISSING,
                        f"{name} has no power jumper",
                        device=name,
                        hint="Call add_device(...) or connect VCC yourself.",
                    )
                )
            if device.needs_ground and not any(
                wire.device == name and wire.is_ground for wire in self._connections
            ):
                findings.append(
                    Diagnostic(
                        Severity.ERROR,
                        Rule.GROUND_MISSING,
                        f"{name} has no ground jumper",
                        device=name,
                        hint="Every peripheral needs a return path.",
                    )
                )
        return findings

    def _check_levels(self) -> list[Diagnostic]:
        """Two different hazards live here, and they are not interchangeable.

        ``LEVEL_MISMATCH`` (error) is about damage: a line that can reach 5 V
        while the other end expects 3.3 V. ``LEVEL_MARGIN`` (warning) is about
        a line that may simply not be recognised by the peripheral.
        """
        findings: list[Diagnostic] = []
        for wire in self._connections:
            device = self._devices.get(wire.device)
            if device is None or not wire.is_data:
                continue
            level = wire.voltage
            if level is None:
                continue
            pin_level = wire.pin.voltage or LogicLevel.THREE_V3

            if wire.direction is Direction.INPUT and level is LogicLevel.FIVE_V:
                if pin_level is LogicLevel.THREE_V3:
                    findings.append(
                        Diagnostic(
                            Severity.ERROR,
                            Rule.LEVEL_MISMATCH,
                            f"{wire.label} drives {level.value} into {wire.pin.label}, "
                            "which is a 3.3 V pin",
                            pin=wire.pin.label,
                            device=wire.device,
                            connector=wire.connector,
                            hint="Fit a divider (1k2/2k2 is the usual HC-SR04 Echo divider).",
                        )
                    )
                if device.logic is LogicLevel.THREE_V3:
                    findings.append(
                        Diagnostic(
                            Severity.ERROR,
                            Rule.LEVEL_MISMATCH,
                            f"{wire.label} emits {level.value} into a {device.logic.value} peripheral",
                            pin=wire.pin.label,
                            device=wire.device,
                            connector=wire.connector,
                        )
                    )

            if wire.direction is not Direction.INPUT and level is LogicLevel.THREE_V3:
                if device.logic is LogicLevel.FIVE_V and wire.declared_voltage is None:
                    findings.append(
                        Diagnostic(
                            Severity.WARNING,
                            Rule.LEVEL_MARGIN,
                            f"{wire.label} is driven at 3.3 V but {wire.device} is declared 5 V only",
                            pin=wire.pin.label,
                            device=wire.device,
                            connector=wire.connector,
                            hint=(
                                "Check VIH in the datasheet, or declare the contact as 3.3 V "
                                "tolerant with Connector(..., voltage=LogicLevel.THREE_V3)."
                            ),
                        )
                    )
            elif wire.direction is not Direction.INPUT and level is LogicLevel.FIVE_V:
                if device.logic is LogicLevel.THREE_V3:
                    findings.append(
                        Diagnostic(
                            Severity.ERROR,
                            Rule.LEVEL_MISMATCH,
                            f"{wire.label} would put {level.value} on a {device.logic.value} peripheral",
                            pin=wire.pin.label,
                            device=wire.device,
                            connector=wire.connector,
                        )
                    )
        return findings

    def _check_analog(self) -> list[Diagnostic]:
        findings: list[Diagnostic] = []
        for wire in self._connections:
            pin = wire.pin
            if pin.capabilities & Capability.ADC2 and self._wifi and wire.is_data:
                findings.append(
                    Diagnostic(
                        Severity.ERROR,
                        Rule.ADC2_WITH_WIFI,
                        f"{pin.label} is an ADC2 pin and ADC2 is unusable while WiFi is on",
                        pin=pin.label,
                        device=wire.device,
                        connector=wire.connector,
                        hint="Move the sensor to ADC1 (GPIO32-39) or drop WiFi.",
                    )
                )
            if pin.is_input_only and wire.signal.needs_pullup and not pin.has_internal_pullup:
                findings.append(
                    Diagnostic(
                        Severity.WARNING,
                        Rule.NO_INTERNAL_PULLUP,
                        f"{pin.label} has no internal pull-up/pull-down",
                        pin=pin.label,
                        device=wire.device,
                        connector=wire.connector,
                        hint=f"Add an external {4_700 if wire.signal in (Signal.I2C_SDA, Signal.I2C_SCL) else 10_000} ohm resistor.",
                    )
                )
            device = self._devices.get(wire.device)
            if (
                device is not None
                and wire.signal in (Signal.I2C_SDA, Signal.I2C_SCL)
                and not device.has_pullups
            ):
                findings.append(
                    Diagnostic(
                        Severity.INFO,
                        Rule.INTERNAL_I2C,
                        f"{wire.label} is an open-drain line and {device.name} declares no pull-ups",
                        pin=pin.label,
                        device=wire.device,
                        connector=wire.connector,
                        hint="Enable the internal pull-ups (pinMode(..., PULLUP)) or fit 4k7 resistors.",
                    )
                )
        return findings

    def _check_coverage(self) -> list[Diagnostic]:
        findings: list[Diagnostic] = []
        wired = {(wire.device, wire.connector) for wire in self._connections}
        for name, device in self._devices.items():
            data_contacts = [
                c for c in device.connectors if _connector_power_kind(c.name) is None
            ]
            unused = [c.name for c in data_contacts if (name, c.name) not in wired]
            if unused:
                findings.append(
                    Diagnostic(
                        Severity.INFO,
                        Rule.CONNECTOR_UNUSED,
                        f"{name} declares {', '.join(unused)} but nothing is wired there",
                        device=name,
                        hint="Remove the declaration or wire the pin.",
                    )
                )
            if not data_contacts and not any(
                wire.device == name and wire.is_data for wire in self._connections
            ):
                findings.append(
                    Diagnostic(
                        Severity.INFO,
                        Rule.DEVICE_UNWIRED,
                        f"{name} is only connected to the power rails",
                        device=name,
                    )
                )
        return findings


def supplies_by_device(supplies: dict[str, list[Connection]]) -> set[str]:
    return {wire.device for wires in supplies.values() for wire in wires}
