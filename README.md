# jumper — ESP32 DevKit V1 wiring plans (Python + C++)

A **senior-grade** library to document, reason about, and validate jumper wire
plans for the **DOIT ESP32 DEVKit V1 (30-pin)**. The core model is immutable,
the rules are explicit, and both language front-ends share the same semantics.

## Philosophy

- **Explicit, not opinionated**: if something could be ambiguous, the library
  reports a diagnostic with a fix hint, not a silent guess.
- **Hardware first**: input-only pins, strapping pins, ADC2+WiFi, 5 V↔3.3 V
  voltage domains and open-drain buses are all modelled.
- **Reproducible by machine and human**: emit tables to paste into a README, or
  JSON to feed into CI.

## Install (Python)

```bash
# from source
python3 -m pip install -e .

# or just run tests with PYTHONPATH=src
PYTHONPATH=src python3 -m unittest discover -s tests -t .
```

## Quick start (Python)

```python
from jumper import (
    DEVKIT_V1, WiringPlan, Device, Connector, Signal, LogicLevel
)

plan = WiringPlan("Weather station", board=DEVKIT_V1)
plan.add_device(Device(
    "BME280",
    logic=LogicLevel.THREE_V3,
    connectors=(
        Connector("SDA", Signal.I2C_SDA),
        Connector("SCL", Signal.I2C_SCL),
    ),
    has_pullups=True,  # board already carries pull-ups
))
plan.wire("BME280", "SDA", "D21")
plan.wire("BME280", "SCL", "D22")
plan.assert_valid()  # raises WiringInvalid if any errors exist
print(plan.render())
```

## CLI

```bash
# Pinout table
python3 -m jumper board

# Validate a JSON plan
python3 -m jumper plan examples/weather.json
python3 -m jumper plan examples/weather.json --json
python3 -m jumper plan examples/weather.json --quiet  # exit 1 on errors only
```

## C++ usage

```cpp
#include <jumper/jumper.hpp>
#include <iostream>

int main() {
    jumper::WiringPlan plan{"Weather station"};
    plan.addDevice({"BME280",
                    jumper::LogicLevel::ThreeV3,
                    {{"SDA", jumper::Signal::I2cSda},
                     {"SCL", jumper::Signal::I2cScl}},
                    true, true, true});  // auto_power, needs_ground, has_pullups
    plan.wire("BME280", "SDA", "D21");
    plan.wire("BME280", "SCL", "D22");
    if (plan.isValid()) {
        plan.render(std::cout);
    } else {
        plan.assertValid();  // throws
    }
}
```

Build and test:

```bash
g++ -std=c++17 -Wall -Wextra -Wpedantic -Icpp/include \
    cpp/tests/test_jumper.cpp cpp/src/jumper.cpp -o /tmp/test_jumper
/tmp/test_jumper
```

## Rules enforced

| Rule ID | Severity | What it catches |
|---|---|---|
| `pin/input-only` | ERROR | Driving GPIO34/35/36/39, or trying to use an input-only pin as open-drain. |
| `pin/strapping` | WARNING | Using any of GPIO0/2/5/12/15 for data lines. Includes a short explanation. |
| `pin/uart0` | WARNING | Wiring to TX0/RX0 (shared with the USB serial monitor). |
| `pin/psram` | WARNING | Using GPIO15 on boards where PSRAM might be active. |
| `pin/already-used` | ERROR | Two different nets on the same GPIO header contact. |
| `pin/no-internal-pullup` | WARNING | Button or I2C line on a pin without an internal pull-up. |
| `adc/adc2-with-wifi` | ERROR | ADC2 pins (GPIO2,4,12,13,14,15,25,26,27) are unusable while WiFi is on. |
| `power/multiple-sources` | ERROR | Feeding the same rail from two different header pins. |
| `power/peripheral-not-powered` | ERROR | A peripheral that needs power was never connected to a rail. |
| `power/peripheral-without-ground` | ERROR | Missing return path for a peripheral. |
| `power/duplicate-ground` | WARNING | Many jumpers on a single GND contact. |
| `power/shared-rail` | INFO | Multiple peripherals share 3V3/VIN (normal for breadboards). |
| `power/level-mismatch` | ERROR | Damaging level mismatch: 5 V pushed into a 3.3 V pin, or 5 V onto a 3.3 V peripheral output path. |
| `power/insufficient-level` | WARNING | A 5 V peripheral is driven at 3.3 V and may not meet VIH (can be waived by declaring the contact as 3.3 V tolerant). |
| `bus/internal-pullups-absent` | INFO | Open-drain buses without declared on-module pull-ups; suggests enabling internal pull-ups or adding 4k7 resistors. |
| `device/connector-unused` | INFO | A declared contact was never wired. |
| `device/not-wired` | INFO | A peripheral is only connected to power/ground. |

## Design notes

- **Grounds are round-robin** across the two GND pins of the DevKit V1 to
  discourage daisy-chaining the entire breadboard through one contact.
- **Voltage is explicit**: for 5 V parts that tolerate 3.3 V logic (HC-SR04
  trigger, many relay modules), declare `Connector(..., voltage=LogicLevel.THREE_V3)`
  to suppress the `LEVEL_MARGIN` warning.
- **ADC split is enforced**: ADC1 (GPIO32,33,34,35,36,39) works with WiFi;
  ADC2 is forbidden while WiFi is active.
- **Bidirectional pins must be output-capable**: an input-only pin cannot
  participate in an open-drain bus like I2C.

## Example plan (JSON)

```json
{
  "name": "Weather station",
  "description": "BME280 over I2C plus a status LED",
  "wifi": true,
  "devices": [
    {
      "name": "BME280",
      "logic": "3.3V",
      "has_pullups": true,
      "connectors": [
        {"name": "SDA", "signal": "I2C_SDA"},
        {"name": "SCL", "signal": "I2C_SCL"}
      ],
      "pins": {"SDA": "D21", "SCL": "D22"}
    }
  ]
}
```

## License

MIT. See [LICENSE](LICENSE).
