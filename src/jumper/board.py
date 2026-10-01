"""Board definitions.

A :class:`Board` is a declarative table: label, GPIO number, physical side and
capability flags. Everything else in the library is derived from it, which
makes adding a new board a matter of adding one table entry per pin.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import get_close_matches
from typing import Iterator, Mapping, Optional, Sequence

from .errors import UnknownPinError
from .model import Capability, Direction, LogicLevel, Signal, Side

__all__ = ["Board", "Pin"]

_OUT = Capability.INPUT | Capability.OUTPUT | Capability.PULLUP | Capability.PULLDOWN
_DIGITAL = _OUT | Capability.PWM | Capability.SPI | Capability.I2C | Capability.UART


def _gpio(
    label: str,
    number: int,
    side: Side,
    caps: Capability,
    *,
    aliases: Sequence[str] = (),
) -> "Pin":
    return Pin(label=label, gpio=number, side=side, capabilities=caps, aliases=tuple(aliases))


@dataclass(frozen=True, slots=True)
class Pin:
    """A single break-out header contact."""

    label: str
    gpio: Optional[int]
    side: Side
    capabilities: Capability
    aliases: tuple[str, ...] = ()
    slot: int = -1
    """Index of the contact in the board table.

    Two ground contacts share the label ``GND``, so the label alone cannot
    identify a wire: the slot can.
    """

    @property
    def is_power(self) -> bool:
        return self.side is Side.POWER

    @property
    def is_ground(self) -> bool:
        return self.label in ("GND",)

    @property
    def voltage(self) -> Optional[LogicLevel]:
        if self.label == "3V3":
            return LogicLevel.THREE_V3
        if self.label in ("VIN", "5V"):
            return LogicLevel.FIVE_V
        return LogicLevel.THREE_V3 if self.gpio is not None else None

    @property
    def is_input_only(self) -> bool:
        return bool(self.capabilities & Capability.INPUT_ONLY)

    @property
    def is_strapping(self) -> bool:
        return bool(self.capabilities & Capability.STRAPPING)

    def supports(self, direction: Direction) -> bool:
        if direction is Direction.SUPPLY:
            return self.is_power
        if direction is Direction.RETURN:
            return self.is_ground
        if direction is Direction.INPUT:
            return bool(self.capabilities & Capability.INPUT)
        if direction is Direction.BIDIRECTIONAL:
            return bool(self.capabilities & Capability.INPUT) and bool(
                self.capabilities & Capability.OUTPUT
            )
        return bool(self.capabilities & Capability.OUTPUT)

    @property
    def has_internal_pullup(self) -> bool:
        return bool(self.capabilities & Capability.PULLUP)


def _devkit_v1() -> tuple[Pin, ...]:
    """Pin table of the DOIT ESP32 DEVKIT V1 (30-pin version).

    Ordered top-to-bottom as printed on the silkscreen, USB connector up.
    """
    left = (
        _gpio("EN", None, Side.LEFT, Capability.NONE, aliases=("reset",)),
        _gpio("VP", 36, Side.LEFT, Capability.INPUT | Capability.ADC1 | Capability.INPUT_ONLY),
        _gpio("VN", 39, Side.LEFT, Capability.INPUT | Capability.ADC1 | Capability.INPUT_ONLY),
        _gpio("D34", 34, Side.LEFT, Capability.INPUT | Capability.ADC1 | Capability.INPUT_ONLY),
        _gpio("D35", 35, Side.LEFT, Capability.INPUT | Capability.ADC1 | Capability.INPUT_ONLY),
        _gpio("D32", 32, Side.LEFT, _DIGITAL | Capability.ADC1 | Capability.TOUCH),
        _gpio("D33", 33, Side.LEFT, _DIGITAL | Capability.ADC1 | Capability.TOUCH),
        _gpio("D25", 25, Side.LEFT, _DIGITAL | Capability.ADC2 | Capability.DAC),
        _gpio("D26", 26, Side.LEFT, _DIGITAL | Capability.ADC2 | Capability.DAC),
        _gpio("D27", 27, Side.LEFT, _DIGITAL | Capability.ADC2 | Capability.TOUCH),
        _gpio("D14", 14, Side.LEFT, _DIGITAL | Capability.ADC2 | Capability.TOUCH),
        _gpio("D13", 13, Side.LEFT, _DIGITAL | Capability.ADC2 | Capability.TOUCH),
        _gpio("D12", 12, Side.LEFT, _DIGITAL | Capability.ADC2 | Capability.STRAPPING),
        Pin("GND", None, Side.POWER, Capability.NONE),
        Pin("VIN", None, Side.POWER, Capability.NONE, aliases=("5V",)),
    )
    right = (
        _gpio("D23", 23, Side.RIGHT, _DIGITAL | Capability.SPI),
        _gpio("D22", 22, Side.RIGHT, _DIGITAL | Capability.I2C, aliases=("SCL",)),
        _gpio("TX0", 1, Side.RIGHT, _DIGITAL | Capability.UART, aliases=("TX", "GPIO1")),
        _gpio("RX0", 3, Side.RIGHT, _DIGITAL | Capability.UART, aliases=("RX", "GPIO3")),
        _gpio("D21", 21, Side.RIGHT, _DIGITAL | Capability.I2C, aliases=("SDA",)),
        _gpio("D19", 19, Side.RIGHT, _DIGITAL | Capability.SPI),
        _gpio("D18", 18, Side.RIGHT, _DIGITAL | Capability.SPI),
        _gpio("D5", 5, Side.RIGHT, _DIGITAL | Capability.STRAPPING),
        _gpio("TX2", 17, Side.RIGHT, _DIGITAL | Capability.UART, aliases=("GPIO17",)),
        _gpio("RX2", 16, Side.RIGHT, _DIGITAL | Capability.UART, aliases=("GPIO16",)),
        _gpio("D4", 4, Side.RIGHT, _DIGITAL | Capability.ADC2 | Capability.TOUCH),
        _gpio("D2", 2, Side.RIGHT, _DIGITAL | Capability.ADC2 | Capability.STRAPPING),
        _gpio("D15", 15, Side.RIGHT, _DIGITAL | Capability.ADC2 | Capability.STRAPPING | Capability.PSRAM),
        Pin("GND", None, Side.POWER, Capability.NONE),
        Pin("3V3", None, Side.POWER, Capability.NONE, aliases=("3.3V",)),
    )
    return left + right


class Board:
    """An immutable, self-checked pin table."""

    def __init__(self, name: str, pins: Sequence[Pin], reserved: Mapping[str, str] | None = None) -> None:
        self.name = name
        self._pins: tuple[Pin, ...] = tuple(
            replace(pin, slot=slot) for slot, pin in enumerate(pins)
        )
        self._by_label: dict[str, Pin] = {}
        self._reserved = dict(reserved or {})
        self._index()
        self._self_check()

    def _index(self) -> None:
        for pin in self._pins:
            for key in (pin.label, *pin.aliases):
                normalised = key.upper()
                existing = self._by_label.get(normalised)
                if existing is not None:
                    if existing.gpio == pin.gpio and pin.gpio is None:
                        continue
                    raise ValueError(f"duplicate pin label {key!r} on board {self.name!r}")
                self._by_label[normalised] = pin

    def _self_check(self) -> None:
        gpios: set[int] = set()
        for pin in self._pins:
            if pin.gpio is None:
                continue
            if pin.gpio in gpios:
                raise ValueError(f"GPIO{pin.gpio} is exposed twice on board {self.name!r}")
            gpios.add(pin.gpio)
            if pin.is_input_only and pin.capabilities & Capability.OUTPUT:
                raise ValueError(f"{pin.label} is marked input-only but also output capable")
            if pin.capabilities & Capability.INPUT_ONLY and not pin.capabilities & Capability.INPUT:
                raise ValueError(f"{pin.label} is input-only but not marked as input capable")

    @property
    def pins(self) -> tuple[Pin, ...]:
        return self._pins

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(pin.label for pin in self._pins)

    @property
    def reserved(self) -> Mapping[str, str]:
        """GPIO numbers that are not exposed on the header, and why."""
        return dict(self._reserved)

    @property
    def ground_labels(self) -> tuple[str, ...]:
        """Every ground contact; the DevKit V1 exposes two."""
        return tuple(pin.label for pin in self._pins if pin.is_ground)

    @property
    def ground_pins(self) -> tuple[Pin, ...]:
        """Ground contacts in table order, so they can be dealt out in turn."""
        return tuple(pin for pin in self._pins if pin.is_ground)

    @property
    def rails(self) -> tuple[tuple[str, LogicLevel], ...]:
        """Power rails as ``(label, voltage)`` pairs."""
        return tuple(
            (pin.label, pin.voltage)
            for pin in self._pins
            if pin.is_power and not pin.is_ground and pin.voltage is not None
        )

    def side(self, side: Side) -> tuple[Pin, ...]:
        return tuple(pin for pin in self._pins if pin.side is side)

    def lookup(self, label: str) -> Pin:
        """Resolve ``label`` (case-insensitive, aliases accepted).

        Raises:
            UnknownPinError: when nothing matches; the exception carries a
                ``suggestion`` when a close match exists.
        """
        key = label.strip().upper()
        pin = self._by_label.get(key)
        if pin is not None:
            return pin
        candidates = [name for name in self._by_label if not name.startswith("GPIO")]
        matches = get_close_matches(key, candidates, n=1, cutoff=0.6)
        raise UnknownPinError(label, matches[0] if matches else None)

    def find(self, label: str) -> Optional[Pin]:
        """Non-raising variant of :meth:`lookup`."""
        try:
            return self.lookup(label)
        except UnknownPinError:
            return None

    def by_gpio(self, number: int) -> Optional[Pin]:
        return next((pin for pin in self._pins if pin.gpio == number), None)

    def rail(self, voltage: LogicLevel, ground: bool = False) -> Pin:
        """Return the power rail pin (``3V3`` / ``VIN``) or a ground pin."""
        if ground:
            ground_pins = [pin for pin in self._pins if pin.is_ground]
            if not ground_pins:
                raise UnknownPinError("GND")
            return ground_pins[0]
        wanted = "3V3" if voltage is LogicLevel.THREE_V3 else "VIN"
        pin = self._by_label.get(wanted)
        if pin is None:
            raise UnknownPinError(wanted)
        return pin

    def __iter__(self) -> Iterator[Pin]:
        return iter(self._pins)

    def __len__(self) -> int:
        return len(self._pins)

    def __repr__(self) -> str:
        return f"Board(name={self.name!r}, pins={len(self._pins)})"


DEVKIT_V1 = Board(
    name="ESP32 DevKit V1 (30-pin)",
    pins=_devkit_v1(),
    reserved={
        "GPIO0": "BOOT button / on-board LED; must be HIGH at reset",
        "GPIO6": "SPI flash",
        "GPIO7": "SPI flash",
        "GPIO8": "SPI flash",
        "GPIO9": "SPI flash / boot log",
        "GPIO10": "SPI flash / boot log",
        "GPIO11": "SPI flash",
    },
)
