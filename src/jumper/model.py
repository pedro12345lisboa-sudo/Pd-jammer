"""Domain model: signals, directions, capabilities and devices.

Everything here is immutable and free of I/O so the model can be reused by
the renderer, the CLI and the validation engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntFlag
from typing import Mapping, Optional

__all__ = [
    "Capability",
    "Connector",
    "Device",
    "Direction",
    "LogicLevel",
    "Signal",
    "Side",
]


class Side(Enum):
    """Physical side of the development board header."""

    LEFT = "left"
    RIGHT = "right"
    POWER = "power"


class Direction(Enum):
    """Who drives the electrical line."""

    OUTPUT = "output"
    """The MCU sources current (drives the line)."""

    INPUT = "input"
    """The peripheral sources current (the MCU senses it)."""

    BIDIRECTIONAL = "bidirectional"
    """Both sides may drive (open-drain buses such as I2C)."""

    SUPPLY = "supply"
    """Power rail feeding a peripheral."""

    RETURN = "return"
    """Ground return path."""

    @property
    def is_data(self) -> bool:
        """True for signal lines, i.e. everything except power and ground."""
        return self not in (Direction.SUPPLY, Direction.RETURN)


class Capability(IntFlag):
    """Peripheral capabilities of a single GPIO."""

    NONE = 0
    INPUT = 1 << 0
    OUTPUT = 1 << 1
    PULLUP = 1 << 2
    PULLDOWN = 1 << 3
    ADC1 = 1 << 4
    ADC2 = 1 << 5
    DAC = 1 << 6
    PWM = 1 << 7
    TOUCH = 1 << 8
    SPI = 1 << 9
    I2C = 1 << 10
    UART = 1 << 11
    INPUT_ONLY = 1 << 12
    FLASH = 1 << 13
    STRAPPING = 1 << 14
    PSRAM = 1 << 15

    def __str__(self) -> str:
        if not self:
            return "-"
        names: list[str] = []
        for flag in Capability:
            if flag.value and self & flag:
                names.extend(_CAPABILITY_NAMES[flag])
        return " ".join(sorted(names))


class LogicLevel(Enum):
    """Voltage domain a peripheral speaks."""

    THREE_V3 = "3.3V"
    FIVE_V = "5V"

    @property
    def millivolts(self) -> int:
        return 3300 if self is LogicLevel.THREE_V3 else 5000


class Signal(Enum):
    """Semantic role of a jumper wire."""

    GROUND = "GND"
    POWER_3V3 = "3V3"
    POWER_5V = "5V"

    I2C_SDA = "I2C_SDA"
    I2C_SCL = "I2C_SCL"
    SPI_SCK = "SPI_SCK"
    SPI_MOSI = "SPI_MOSI"
    SPI_MISO = "SPI_MISO"
    SPI_CS = "SPI_CS"
    UART_TX = "UART_TX"
    UART_RX = "UART_RX"

    GPIO_OUT = "GPIO_OUT"
    GPIO_IN = "GPIO_IN"
    PWM_OUT = "PWM_OUT"
    ADC_READ = "ADC_READ"
    TRIGGER_OUT = "TRIGGER_OUT"
    SENSOR_IN = "SENSOR_IN"
    BUTTON_IN = "BUTTON_IN"
    OTHER = "OTHER"

    @property
    def default_direction(self) -> Direction:
        return _SIGNAL_DIRECTIONS[self]

    @property
    def voltage(self) -> Optional[LogicLevel]:
        """Logic voltage carried by the signal; ``None`` when not applicable."""
        return _SIGNAL_VOLTAGE.get(self)

    @property
    def needs_pullup(self) -> bool:
        return self in (Signal.I2C_SDA, Signal.I2C_SCL, Signal.BUTTON_IN)


_SIGNAL_DIRECTIONS: Mapping[Signal, Direction] = {
    Signal.GROUND: Direction.RETURN,
    Signal.POWER_3V3: Direction.SUPPLY,
    Signal.POWER_5V: Direction.SUPPLY,
    Signal.I2C_SDA: Direction.BIDIRECTIONAL,
    Signal.I2C_SCL: Direction.BIDIRECTIONAL,
    Signal.SPI_SCK: Direction.OUTPUT,
    Signal.SPI_MOSI: Direction.OUTPUT,
    Signal.SPI_MISO: Direction.INPUT,
    Signal.SPI_CS: Direction.OUTPUT,
    Signal.UART_TX: Direction.OUTPUT,
    Signal.UART_RX: Direction.INPUT,
    Signal.GPIO_OUT: Direction.OUTPUT,
    Signal.GPIO_IN: Direction.INPUT,
    Signal.PWM_OUT: Direction.OUTPUT,
    Signal.ADC_READ: Direction.INPUT,
    Signal.TRIGGER_OUT: Direction.OUTPUT,
    Signal.SENSOR_IN: Direction.INPUT,
    Signal.BUTTON_IN: Direction.INPUT,
    Signal.OTHER: Direction.BIDIRECTIONAL,
}

_SIGNAL_VOLTAGE: Mapping[Signal, Optional[LogicLevel]] = {
    Signal.POWER_3V3: LogicLevel.THREE_V3,
    Signal.POWER_5V: LogicLevel.FIVE_V,
    Signal.I2C_SDA: LogicLevel.THREE_V3,
    Signal.I2C_SCL: LogicLevel.THREE_V3,
    Signal.UART_TX: LogicLevel.THREE_V3,
    Signal.UART_RX: LogicLevel.THREE_V3,
    Signal.GPIO_OUT: LogicLevel.THREE_V3,
    Signal.GPIO_IN: LogicLevel.THREE_V3,
    Signal.PWM_OUT: LogicLevel.THREE_V3,
    Signal.TRIGGER_OUT: LogicLevel.THREE_V3,
    Signal.SENSOR_IN: LogicLevel.THREE_V3,
    Signal.BUTTON_IN: LogicLevel.THREE_V3,
    Signal.ADC_READ: LogicLevel.THREE_V3,
    Signal.SPI_SCK: LogicLevel.THREE_V3,
    Signal.SPI_MOSI: LogicLevel.THREE_V3,
    Signal.SPI_CS: LogicLevel.THREE_V3,
}

_CAPABILITY_NAMES: Mapping[Capability, tuple[str, ...]] = {
    Capability.INPUT: ("input",),
    Capability.OUTPUT: ("output",),
    Capability.PULLUP: ("pull-up",),
    Capability.PULLDOWN: ("pull-down",),
    Capability.ADC1: ("adc1",),
    Capability.ADC2: ("adc2",),
    Capability.DAC: ("dac",),
    Capability.PWM: ("pwm",),
    Capability.TOUCH: ("touch",),
    Capability.SPI: ("spi",),
    Capability.I2C: ("i2c",),
    Capability.UART: ("uart",),
    Capability.INPUT_ONLY: ("input-only",),
    Capability.FLASH: ("flash",),
    Capability.STRAPPING: ("strapping",),
    Capability.PSRAM: ("psram",),
}


@dataclass(frozen=True, slots=True)
class Connector:
    """A labelled contact on a peripheral.

    ``voltage`` overrides what the signal name implies, which matters for parts
    that are powered at 5 V but tolerate 3.3 V logic (HC-SR04 trigger, most
    5 V relay boards' inputs).
    """

    name: str
    signal: Signal
    direction: Optional[Direction] = None
    requires_pullup: Optional[bool] = None
    voltage: Optional[LogicLevel] = None

    @property
    def resolved_direction(self) -> Direction:
        return self.direction or self.signal.default_direction

    @property
    def resolved_pullup(self) -> bool:
        if self.requires_pullup is not None:
            return self.requires_pullup
        return self.signal.needs_pullup

    @property
    def resolved_voltage(self) -> Optional[LogicLevel]:
        return self.voltage or self.signal.voltage


@dataclass(frozen=True, slots=True)
class Device:
    """A peripheral wired to the board."""

    name: str
    logic: LogicLevel = LogicLevel.THREE_V3
    connectors: tuple[Connector, ...] = ()
    needs_power: bool = True
    needs_ground: bool = True
    has_pullups: bool = False
    notes: str = field(default="", compare=False)

    def connector(self, name: str) -> Connector:
        """Return the connector called ``name``.

        Raises:
            UnknownConnectorError: when the peripheral has no such contact.
        """
        for candidate in self.connectors:
            if candidate.name == name:
                return candidate
        from .errors import UnknownConnectorError

        raise UnknownConnectorError(self.name, name, (c.name for c in self.connectors))
