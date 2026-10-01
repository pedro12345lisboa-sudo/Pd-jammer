#include "jumper/jumper.hpp"

#include <algorithm>
#include <cctype>
#include <iomanip>
#include <map>
#include <ostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <tuple>

namespace jumper {
namespace {

std::string upper(std::string_view text) {
    std::string out(text);
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::toupper(c));
    });
    return out;
}

std::string_view trim(std::string_view text) {
    std::size_t begin = 0;
    std::size_t end = text.size();
    while (begin < end && std::isspace(static_cast<unsigned char>(text[begin]))) ++begin;
    while (end > begin && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    return text.substr(begin, end - begin);
}

std::vector<std::string_view> split(std::string_view text, char separator) {
    std::vector<std::string_view> parts;
    std::size_t start = 0;
    while (true) {
        const std::size_t hit = text.find(separator, start);
        if (hit == std::string_view::npos) {
            parts.push_back(text.substr(start));
            break;
        }
        parts.push_back(text.substr(start, hit - start));
        start = hit + 1;
    }
    return parts;
}

constexpr Capability kDigital = Capability::Input | Capability::Output | Capability::PullUp |
                                Capability::PullDown | Capability::Pwm | Capability::Spi |
                                Capability::I2c | Capability::Uart;
constexpr Capability kInputOnlyAdc = Capability::Input | Capability::Adc1 | Capability::InputOnly;

/// Human explanation for a strapping pin, when one exists.
std::string strappingNote(std::optional<int> number) {
    if (!number) return {};
    switch (*number) {
        case 0: return "GPIO0 is sampled at reset: pull LOW to enter the bootloader.";
        case 2: return "GPIO2 must be LOW or floating at reset; it drives the on-board LED.";
        case 5: return "GPIO5 must be HIGH at reset (internal pull-up).";
        case 12:
            return "GPIO12 must be LOW at reset; the internal pull-down already forces this, so "
                   "an external pull-up stops the chip from booting.";
        case 15: return "GPIO15 must be HIGH at reset (internal pull-up).";
        default: return "This pin is sampled at reset.";
    }
}

bool isPowerConnector(std::string_view name) {
    const std::string key = upper(name);
    return key == "VCC" || key == "VIN" || key == "+" || key == "5V" || key == "3V3";
}

bool isGroundConnector(std::string_view name) { return upper(name) == "GND" || name == "-"; }

std::string escapeJson(std::string_view text) {
    std::string out;
    out.reserve(text.size() + 2);
    for (const char c : text) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\t': out += "\\t"; break;
            default: out += c; break;
        }
    }
    return out;
}

}  // namespace

// ---------------------------------------------------------------------------
// Pin
// ---------------------------------------------------------------------------

std::optional<LogicLevel> Pin::voltage() const noexcept {
    if (label == "3V3") return LogicLevel::ThreeV3;
    if (label == "VIN" || label == "5V") return LogicLevel::FiveV;
    if (gpio) return LogicLevel::ThreeV3;
    return std::nullopt;
}

bool Pin::supports(Direction direction) const noexcept {
    switch (direction) {
        case Direction::Supply: return isPower();
        case Direction::Return: return isGround();
        case Direction::Input: return any(capabilities & Capability::Input);
        case Direction::Bidirectional:
            return any(capabilities & Capability::Input) && any(capabilities & Capability::Output);
        case Direction::Output: return any(capabilities & Capability::Output);
    }
    return false;
}

bool Pin::matches(std::string_view key) const noexcept {
    const std::string needle = upper(key);
    if (upper(label) == needle) return true;
    for (const std::string_view alias : split(aliases, ',')) {
        if (alias.empty()) continue;
        if (upper(alias) == needle) return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

UnknownPin::UnknownPin(std::string label, std::optional<std::string> suggestion)
    : Error([&] {
          std::string text = "unknown pin '" + label + "'";
          if (suggestion) text += "; did you mean '" + *suggestion + "'?";
          return text;
      }()),
      label_(std::move(label)),
      suggestion_(std::move(suggestion)) {}

UnknownConnector::UnknownConnector(std::string device, std::string connector, std::string available)
    : Error("device '" + device + "' has no connector '" + connector + "'; available: " +
            (available.empty() ? "<none>" : available)) {}

DuplicateDevice::DuplicateDevice(const std::string& name)
    : Error("device '" + name + "' is already registered") {}

WiringInvalid::WiringInvalid(std::vector<Diagnostic> diagnostics, std::string message)
    : Error(std::move(message)), diagnostics_(std::move(diagnostics)) {}

// ---------------------------------------------------------------------------
// Board
// ---------------------------------------------------------------------------

Board::Board(std::string name, std::vector<Pin> pins,
             std::vector<std::pair<std::string, std::string>> reserved)
    : name_(std::move(name)), pins_(std::move(pins)), reserved_(std::move(reserved)) {
    selfCheck();
}

void Board::selfCheck() const {
    std::set<int> gpios;
    std::set<std::string> labels;
    for (const Pin& pin : pins_) {
        // GND appears twice by design: one contact per edge of the board.
        if (pin.gpio && !labels.insert(upper(pin.label)).second) {
            throw std::logic_error("duplicate pin label '" + std::string(pin.label) + "' on board " +
                                   name_);
        }
        if (!pin.gpio) labels.insert(upper(pin.label));
        if (pin.gpio && !gpios.insert(*pin.gpio).second) {
            throw std::logic_error("GPIO" + std::to_string(*pin.gpio) + " is exposed twice on board " +
                                   name_);
        }
        if (pin.isInputOnly() && any(pin.capabilities & Capability::Output)) {
            throw std::logic_error(std::string(pin.label) +
                                   " is marked input-only but also output capable");
        }
    }
}

const Board& Board::devkitV1() {
    static const Board board = [] {
        std::vector<Pin> pins = {
            // Left edge, top to bottom, USB connector up.
            Pin{"EN", std::nullopt, Side::Left, Capability::None, "reset"},
            Pin{"VP", 36, Side::Left, kInputOnlyAdc, {}},
            Pin{"VN", 39, Side::Left, kInputOnlyAdc, {}},
            Pin{"D34", 34, Side::Left, kInputOnlyAdc, {}},
            Pin{"D35", 35, Side::Left, kInputOnlyAdc, {}},
            Pin{"D32", 32, Side::Left, kDigital | Capability::Adc1 | Capability::Touch, {}},
            Pin{"D33", 33, Side::Left, kDigital | Capability::Adc1 | Capability::Touch, {}},
            Pin{"D25", 25, Side::Left, kDigital | Capability::Adc2 | Capability::Dac, {}},
            Pin{"D26", 26, Side::Left, kDigital | Capability::Adc2 | Capability::Dac, {}},
            Pin{"D27", 27, Side::Left, kDigital | Capability::Adc2 | Capability::Touch, {}},
            Pin{"D14", 14, Side::Left, kDigital | Capability::Adc2 | Capability::Touch, {}},
            Pin{"D13", 13, Side::Left, kDigital | Capability::Adc2 | Capability::Touch, {}},
            Pin{"D12", 12, Side::Left, kDigital | Capability::Adc2 | Capability::Strapping, {}},
            Pin{"GND", std::nullopt, Side::Power, Capability::None, {}},
            Pin{"VIN", std::nullopt, Side::Power, Capability::None, "5V"},
            // Right edge, top to bottom.
            Pin{"D23", 23, Side::Right, kDigital | Capability::Spi, {}},
            Pin{"D22", 22, Side::Right, kDigital | Capability::I2c, "SCL"},
            Pin{"TX0", 1, Side::Right, kDigital | Capability::Uart, "TX,GPIO1"},
            Pin{"RX0", 3, Side::Right, kDigital | Capability::Uart, "RX,GPIO3"},
            Pin{"D21", 21, Side::Right, kDigital | Capability::I2c, "SDA"},
            Pin{"D19", 19, Side::Right, kDigital | Capability::Spi, {}},
            Pin{"D18", 18, Side::Right, kDigital | Capability::Spi, {}},
            Pin{"D5", 5, Side::Right, kDigital | Capability::Strapping, {}},
            Pin{"TX2", 17, Side::Right, kDigital | Capability::Uart, "GPIO17"},
            Pin{"RX2", 16, Side::Right, kDigital | Capability::Uart, "GPIO16"},
            Pin{"D4", 4, Side::Right, kDigital | Capability::Adc2 | Capability::Touch, {}},
            Pin{"D2", 2, Side::Right, kDigital | Capability::Adc2 | Capability::Strapping, {}},
            Pin{"D15", 15, Side::Right,
                kDigital | Capability::Adc2 | Capability::Strapping | Capability::Psram, {}},
            Pin{"GND", std::nullopt, Side::Power, Capability::None, {}},
            Pin{"3V3", std::nullopt, Side::Power, Capability::None, "3.3V"},
        };
        return Board("ESP32 DevKit V1 (30-pin)", std::move(pins),
                     {{"GPIO0", "BOOT button / on-board LED; must be HIGH at reset"},
                      {"GPIO6", "SPI flash"},
                      {"GPIO7", "SPI flash"},
                      {"GPIO8", "SPI flash"},
                      {"GPIO9", "SPI flash / boot log"},
                      {"GPIO10", "SPI flash / boot log"},
                      {"GPIO11", "SPI flash"}});
    }();
    return board;
}

std::vector<std::string> Board::groundLabels() const {
    std::vector<std::string> labels;
    for (const Pin& pin : pins_) {
        if (pin.isGround()) labels.emplace_back(pin.label);
    }
    return labels;
}

std::vector<const Pin*> Board::groundPins() const {
    std::vector<const Pin*> pins;
    for (const Pin& pin : pins_) {
        if (pin.isGround()) pins.push_back(&pin);
    }
    return pins;
}

const Pin* Board::find(std::string_view label) const noexcept {
    const std::string_view key = trim(label);
    for (const Pin& pin : pins_) {
        if (pin.matches(key)) return &pin;
    }
    return nullptr;
}

const Pin& Board::lookup(std::string_view label) const {
    if (const Pin* pin = find(label)) return *pin;

    std::optional<std::string> suggestion;
    const std::string needle = upper(trim(label));
    std::size_t best = 0;
    for (const Pin& pin : pins_) {
        if (!pin.gpio) continue;
        const std::string candidate = upper(pin.label);
        const std::size_t common = [needle, &candidate] {
            std::size_t hits = 0;
            for (const char a : needle) {
                if (candidate.find(a) != std::string::npos) ++hits;
            }
            return hits;
        }();
        const std::size_t ratio = common * 100 / std::max<std::size_t>(needle.size(), 1);
        if (ratio >= 60 && ratio > best) {
            best = ratio;
            suggestion = std::string(pin.label);
        }
    }
    throw UnknownPin(std::string(trim(label)), suggestion);
}

const Pin& Board::rail(LogicLevel level, bool ground) const {
    if (ground) {
        for (const Pin& pin : pins_) {
            if (pin.isGround()) return pin;
        }
        throw UnknownPin("GND", std::nullopt);
    }
    const std::string_view wanted = level == LogicLevel::ThreeV3 ? "3V3" : "VIN";
    for (const Pin& pin : pins_) {
        if (pin.matches(wanted) && pin.isPower()) return pin;
    }
    throw UnknownPin(std::string(wanted), std::nullopt);
}

// ---------------------------------------------------------------------------
// Device
// ---------------------------------------------------------------------------

const Connector& Device::connector(const std::string& name) const {
    for (const Connector& candidate : connectors) {
        if (candidate.name == name) return candidate;
    }
    std::string available;
    for (const Connector& candidate : connectors) {
        if (!available.empty()) available += ", ";
        available += candidate.name;
    }
    throw UnknownConnector(this->name, name, available);
}

// ---------------------------------------------------------------------------
// WiringPlan
// ---------------------------------------------------------------------------

WiringPlan::WiringPlan(std::string name, const Board& board)
    : name_(std::move(name)), board_(board) {}

WiringPlan& WiringPlan::enableWifi(bool enabled) noexcept {
    wifi_ = enabled;
    return *this;
}

const Device* WiringPlan::findDevice(const std::string& name) const noexcept {
    for (const Device& device : devices_) {
        if (device.name == name) return &device;
    }
    return nullptr;
}

const Pin& WiringPlan::nextGroundPin() {
    const std::vector<const Pin*> pins = board_.groundPins();
    if (pins.empty()) return board_.rail(LogicLevel::ThreeV3, true);
    const Pin* chosen = pins[groundCursor_ % pins.size()];
    ++groundCursor_;
    return *chosen;
}

WiringPlan& WiringPlan::addDevice(Device device, bool autoPower) {
    if (findDevice(device.name) != nullptr) throw DuplicateDevice(device.name);

    if (autoPower && device.needsPower) {
        const Pin& rail = board_.rail(device.logic);
        connect(rail.label,
                device.logic == LogicLevel::ThreeV3 ? Signal::Power3v3 : Signal::Power5v, device.name,
                "VCC");
    }
    if (autoPower && device.needsGround) {
        connect(nextGroundPin(), Signal::Ground, device.name, "GND");
    }
    devices_.push_back(std::move(device));
    return *this;
}

WiringPlan& WiringPlan::connect(const Pin& resolved, Signal signal, std::string device,
                                std::string connector, std::optional<Direction> direction,
                                std::optional<LogicLevel> voltage, std::string note) {
    Connection wire;
    wire.pin = resolved;
    wire.signal = signal;
    wire.device = std::move(device);
    wire.connector = std::move(connector);
    wire.direction = direction.value_or(defaultDirection(signal));
    wire.note = std::move(note);
    wire.declaredVoltage = voltage;
    connections_.push_back(std::move(wire));
    return *this;
}


WiringPlan& WiringPlan::connect(std::string_view pin, Signal signal, std::string device,
                                std::string connector, std::optional<Direction> direction,
                                std::optional<LogicLevel> voltage, std::string note) {
    const Pin& resolved = board_.lookup(pin);
    return connect(resolved, signal, std::move(device), std::move(connector), direction, voltage, std::move(note));
}

WiringPlan& WiringPlan::wire(const std::string& device, const std::string& connector,
                             std::string_view pin, std::string note) {
    const Device* declared = findDevice(device);
    if (declared == nullptr) throw UnknownConnector(device, connector, {});
    const Connector& contact = declared->connector(connector);
    return connect(pin, contact.signal, device, connector, contact.resolvedDirection(),
                   contact.voltage, note.empty() ? declared->notes : std::move(note));
}

std::vector<std::string> WiringPlan::freeLabels(bool includeInputOnly) const {
    std::set<std::string> used;
    for (const Connection& wire : connections_) used.insert(std::string(wire.pin.label));

    std::vector<std::string> labels;
    for (const Pin& pin : board_.pins()) {
        if (used.count(std::string(pin.label)) != 0) continue;
        if (!pin.gpio) continue;
        if (!includeInputOnly && pin.isInputOnly()) continue;
        labels.emplace_back(pin.label);
    }
    return labels;
}

void WiringPlan::checkPinCapabilities(std::vector<Diagnostic>& out) const {
    for (const Connection& wire : connections_) {
        const Pin& pin = wire.pin;
        if (!pin.supports(wire.direction)) {
            Diagnostic finding{Severity::Error, Rule::PinInputOnly, {}, std::string(pin.label),
                               wire.device, wire.connector, std::nullopt};
            if (wire.direction == Direction::Output && pin.isInputOnly()) {
                finding.message = std::string(pin.label) + " is input-only and cannot be driven by the MCU";
                finding.hint = "GPIO34/35/36/39 have no output driver; pick another pin.";
            } else if (wire.direction == Direction::Supply) {
                finding.message = std::string(pin.label) + " is a GPIO, not a power rail";
                finding.hint = "Use 3V3 for 3.3 V or VIN for 5 V.";
            } else if (wire.direction == Direction::Return) {
                finding.message = std::string(pin.label) + " is a GPIO, not a ground rail";
                finding.hint = "Ground jumpers must land on GND.";
            } else if (wire.direction == Direction::Bidirectional) {
                finding.message = std::string(pin.label) +
                                  " has no output driver, so it cannot take part in an open-drain line";
                finding.hint = "I2C needs to pull the line low; move the bus to a regular GPIO.";
            } else {
                finding.message = std::string(pin.label) + " cannot be read as " +
                                  std::string(toString(wire.direction));
            }
            out.push_back(std::move(finding));
        }

        if (pin.isStrapping() && wire.isData()) {
            const std::string note = strappingNote(pin.gpio);
            out.push_back({Severity::Warning, Rule::PinStrapping,
                           std::string(pin.label) + " is a strapping pin and is sampled at reset",
                           std::string(pin.label), wire.device, wire.connector,
                           note.empty() ? std::optional<std::string>{} : std::optional<std::string>{note}});
        }

        if ((pin.label == "TX0" || pin.label == "RX0") && wire.isData()) {
            out.push_back({Severity::Warning, Rule::PinUart0,
                           std::string(pin.label) + " shares UART0 with the USB serial monitor",
                           std::string(pin.label), wire.device, wire.connector,
                           std::string("Use UART2 (TX2/RX2 = GPIO17/GPIO16) for other serial devices.")});
        }

        if (any(pin.capabilities & Capability::Psram) && wire.isData()) {
            out.push_back({Severity::Warning, Rule::PinPsram,
                           std::string(pin.label) + " is used by PSRAM on WROVER modules",
                           std::string(pin.label), wire.device, wire.connector,
                           std::string("Keep this pin only on bare WROOM modules.")});
        }
    }
}

void WiringPlan::checkSingleUse(std::vector<Diagnostic>& out) const {
    const std::vector<std::string> groundLabels = board_.groundLabels();
    std::vector<const Connection*> groundWires;
    for (const Connection& wire : connections_) {
        if (wire.isGround()) groundWires.push_back(&wire);
    }
    const std::size_t capacity =
        groundLabels.empty() ? 1 : (groundWires.size() + groundLabels.size() - 1) / groundLabels.size();

    std::map<std::string, std::vector<const Connection*>> byLabel;
    for (const Connection& wire : connections_) {
        if (wire.isPower()) continue;
        byLabel[std::string(wire.pin.label)].push_back(&wire);
    }

    for (const auto& [label, wires] : byLabel) {
        if (wires.size() <= 1) continue;
        if (std::find(groundLabels.begin(), groundLabels.end(), label) != groundLabels.end()) {
            if (wires.size() > capacity) {
                out.push_back({Severity::Warning, Rule::GroundDuplicated,
                               "GND carries " + std::to_string(wires.size()) + " jumpers and the board offers " +
                                   std::to_string(groundLabels.size()) + " ground contacts",
                               label, std::nullopt, std::nullopt,
                               std::string("Spread them over every GND pin, or feed a ground rail on the "
                                           "breadboard and hang the peripherals from it.")});
            }
            continue;
        }
        std::string endpoints;
        for (const Connection* wire : wires) {
            if (!endpoints.empty()) endpoints += ", ";
            endpoints += wire->label();
        }
        out.push_back({Severity::Error, Rule::PinAlreadyUsed,
                       label + " is wired to " + endpoints, label, std::nullopt, std::nullopt,
                       std::string("One header contact takes one jumper. Add a bus or choose another pin.")});
    }

    std::map<std::string, std::set<std::string>> rails;
    for (const Connection& wire : connections_) {
        if (wire.isPower()) rails[std::string(wire.pin.label)].insert(wire.device);
    }
    for (const auto& [label, devices] : rails) {
        if (devices.size() <= 1) continue;
        std::string joined;
        for (const std::string& device : devices) {
            if (!joined.empty()) joined += ", ";
            joined += device;
        }
        out.push_back({Severity::Info, Rule::PowerRailShared,
                       label + " powers " + std::to_string(devices.size()) + " peripherals (" + joined + ")",
                       label, std::nullopt, std::nullopt,
                       std::string("Keep one jumper from the header to the breadboard rail.")});
    }
}

void WiringPlan::checkGroundAndPower(std::vector<Diagnostic>& out) const {
    std::map<std::string, std::set<std::string>> sources;
    std::map<std::string, std::set<std::string>> poweredDevices;

    for (const Connection& wire : connections_) {
        if (!wire.isPower()) continue;
        const std::string key = wire.pin.voltage() ? std::string(toString(*wire.pin.voltage())) : "?";
        sources[key].insert(std::string(wire.pin.label));
        poweredDevices[key].insert(wire.device);
    }

    for (const auto& [voltage, labels] : sources) {
        if (labels.size() <= 1) continue;
        std::string joined;
        for (const std::string& label : labels) {
            if (!joined.empty()) joined += ", ";
            joined += label;
        }
        out.push_back({Severity::Error, Rule::PowerConflict,
                       "the " + voltage + " rail is fed from both " + joined, std::nullopt,
                       std::nullopt, std::nullopt, std::string("Pick one source per voltage domain.")});
    }

    for (const Connection& wire : connections_) {
        if (!wire.isPower()) continue;
        const std::optional<LogicLevel> railLevel = wire.pin.voltage();
        const std::optional<LogicLevel> wantLevel = signalVoltage(wire.signal);
        if (!railLevel || !wantLevel || *railLevel == *wantLevel) continue;
        out.push_back({Severity::Error, Rule::PowerConflict,
                       wire.label() + " expects " + std::string(toString(*wantLevel)) + " but " +
                           std::string(wire.pin.label) + " is the " + std::string(toString(*railLevel)) +
                           " rail",
                       std::string(wire.pin.label), wire.device, wire.connector,
                       std::string("3.3 V peripherals belong on 3V3, never on VIN.")});
    }

    for (const Device& device : devices_) {
        bool powered = false;
        bool grounded = false;
        for (const auto& [key, devices] : poweredDevices) {
            (void)key;
            if (devices.count(device.name) != 0) powered = true;
        }
        for (const Connection& wire : connections_) {
            if (wire.device == device.name && wire.isGround()) grounded = true;
        }
        if (device.needsPower && !powered) {
            out.push_back({Severity::Error, Rule::PowerMissing, device.name + " has no power jumper",
                           std::nullopt, device.name, std::nullopt,
                           std::string("Call addDevice(...) or connect VCC yourself.")});
        }
        if (device.needsGround && !grounded) {
            out.push_back({Severity::Error, Rule::GroundMissing, device.name + " has no ground jumper",
                           std::nullopt, device.name, std::nullopt,
                           std::string("Every peripheral needs a return path.")});
        }
    }
}

void WiringPlan::checkLevels(std::vector<Diagnostic>& out) const {
    for (const Connection& wire : connections_) {
        const Device* device = findDevice(wire.device);
        if (device == nullptr || !wire.isData()) continue;
        const std::optional<LogicLevel> level = wire.voltage();
        if (!level) continue;
        const LogicLevel pinLevel = wire.pin.voltage().value_or(LogicLevel::ThreeV3);

        if (wire.direction == Direction::Input && *level == LogicLevel::FiveV) {
            if (pinLevel == LogicLevel::ThreeV3) {
                out.push_back({Severity::Error, Rule::LevelMismatch,
                               wire.label() + " drives 5V into " + std::string(wire.pin.label) +
                                   ", which is a 3.3 V pin",
                               std::string(wire.pin.label), wire.device, wire.connector,
                               std::string("Fit a divider (1k2/2k2 is the usual HC-SR04 Echo divider).")});
            }
            if (device->logic == LogicLevel::ThreeV3) {
                out.push_back({Severity::Error, Rule::LevelMismatch,
                               wire.label() + " emits 5V into a 3.3V peripheral",
                               std::string(wire.pin.label), wire.device, wire.connector, std::nullopt});
            }
        }

        if (wire.direction != Direction::Input && *level == LogicLevel::ThreeV3) {
            if (device->logic == LogicLevel::FiveV && !wire.declaredVoltage) {
                out.push_back({Severity::Warning, Rule::LevelMargin,
                               wire.label() + " is driven at 3.3 V but " + wire.device +
                                   " is declared 5 V only",
                               std::string(wire.pin.label), wire.device, wire.connector,
                               std::string("Check VIH in the datasheet, or declare the contact as 3.3 V "
                                           "tolerant with Connector(..., voltage=LogicLevel::ThreeV3).")});
            }
        } else if (wire.direction != Direction::Input && *level == LogicLevel::FiveV) {
            if (device->logic == LogicLevel::ThreeV3) {
                out.push_back({Severity::Error, Rule::LevelMismatch,
                               wire.label() + " would put 5V on a 3.3V peripheral",
                               std::string(wire.pin.label), wire.device, wire.connector, std::nullopt});
            }
        }
    }
}

void WiringPlan::checkAnalog(std::vector<Diagnostic>& out) const {
    for (const Connection& wire : connections_) {
        const Pin& pin = wire.pin;
        if (any(pin.capabilities & Capability::Adc2) && wifi_ && wire.isData()) {
            out.push_back({Severity::Error, Rule::Adc2WithWifi,
                           std::string(pin.label) +
                               " is an ADC2 pin and ADC2 is unusable while WiFi is on",
                           std::string(pin.label), wire.device, wire.connector,
                           std::string("Move the sensor to ADC1 (GPIO32-39) or drop WiFi.")});
        }
        if (pin.isInputOnly() && needsPullup(wire.signal) && !pin.hasInternalPullup()) {
            const bool bus = wire.signal == Signal::I2cSda || wire.signal == Signal::I2cScl;
            out.push_back({Severity::Warning, Rule::NoInternalPullup,
                           std::string(pin.label) + " has no internal pull-up/pull-down",
                           std::string(pin.label), wire.device, wire.connector,
                           "Add an external " + std::string(bus ? "4700" : "10000") + " ohm resistor."});
        }
        const Device* device = findDevice(wire.device);
        if (device != nullptr && (wire.signal == Signal::I2cSda || wire.signal == Signal::I2cScl) &&
            !device->hasPullups) {
            out.push_back({Severity::Info, Rule::InternalI2c,
                           wire.label() + " is an open-drain line and " + device->name +
                               " declares no pull-ups",
                           std::string(pin.label), wire.device, wire.connector,
                           std::string("Enable the internal pull-ups (pinMode(..., PULLUP)) or fit 4k7 "
                                       "resistors.")});
        }
    }
}

void WiringPlan::checkCoverage(std::vector<Diagnostic>& out) const {
    std::set<std::string> wired;
    for (const Connection& wire : connections_) {
        wired.insert(wire.device + "\x1f" + wire.connector);
    }

    for (const Device& device : devices_) {
        std::vector<std::string> dataContacts;
        for (const Connector& connector : device.connectors) {
            if (!isPowerConnector(connector.name) && !isGroundConnector(connector.name)) {
                dataContacts.push_back(connector.name);
            }
        }

        std::string unused;
        for (const std::string& name : dataContacts) {
            if (wired.count(device.name + "\x1f" + name) != 0) continue;
            if (!unused.empty()) unused += ", ";
            unused += name;
        }
        if (!unused.empty()) {
            out.push_back({Severity::Info, Rule::ConnectorUnused,
                           device.name + " declares " + unused + " but nothing is wired there",
                           std::nullopt, device.name, std::nullopt,
                           std::string("Remove the declaration or wire the pin.")});
        }

        if (dataContacts.empty()) {
            bool anyData = false;
            for (const Connection& wire : connections_) {
                if (wire.device == device.name && wire.isData()) anyData = true;
            }
            if (!anyData) {
                out.push_back({Severity::Info, Rule::DeviceUnwired,
                               device.name + " is only connected to the power rails", std::nullopt,
                               device.name, std::nullopt, std::nullopt});
            }
        }
    }
}

std::vector<Diagnostic> WiringPlan::validate() const {
    std::vector<Diagnostic> findings;
    checkPinCapabilities(findings);
    checkSingleUse(findings);
    checkGroundAndPower(findings);
    checkLevels(findings);
    checkAnalog(findings);
    checkCoverage(findings);

    std::stable_sort(findings.begin(), findings.end(), [](const Diagnostic& lhs, const Diagnostic& rhs) {
        const int bySeverity = rank(rhs.severity) - rank(lhs.severity);
        if (bySeverity != 0) return bySeverity < 0;
        return toString(lhs.rule) < toString(rhs.rule);
    });
    return findings;
}

std::vector<Diagnostic> WiringPlan::errors() const {
    std::vector<Diagnostic> out;
    for (const Diagnostic& finding : validate()) {
        if (finding.severity == Severity::Error) out.push_back(finding);
    }
    return out;
}

std::vector<Diagnostic> WiringPlan::warnings() const {
    std::vector<Diagnostic> out;
    for (const Diagnostic& finding : validate()) {
        if (finding.severity == Severity::Warning) out.push_back(finding);
    }
    return out;
}

const WiringPlan& WiringPlan::assertValid() const {
    std::vector<Diagnostic> found = errors();
    if (found.empty()) return *this;

    std::ostringstream message;
    message << "wiring plan is invalid:";
    for (const Diagnostic& finding : found) {
        message << "\n  [" << toString(finding.severity) << "] " << toString(finding.rule) << ": "
                << finding.message;
    }
    throw WiringInvalid(std::move(found), message.str());
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

namespace {

void renderRow(std::ostream& out, const std::vector<std::string>& cells,
               const std::vector<std::size_t>& widths) {
    for (std::size_t index = 0; index < cells.size(); ++index) {
        out << cells[index];
        if (index + 1 < cells.size()) {
            const std::size_t padding =
                widths[index] > cells[index].size() ? widths[index] - cells[index].size() : 0;
            out << std::string(padding, ' ') << "  ";
        }
    }
    out << '\n';
}

std::string pinVoltage(const Pin& pin) {
    return pin.voltage() ? std::string(toString(*pin.voltage())) : std::string("-");
}

}  // namespace

void renderDiagnostic(std::ostream& out, const Diagnostic& diagnostic) {
    const char* glyph = diagnostic.severity == Severity::Error     ? "x"
                        : diagnostic.severity == Severity::Warning ? "!"
                                                                   : "i";
    out << "  " << glyph << ' ' << std::setw(30) << std::left << toString(diagnostic.rule) << ' '
        << diagnostic.message;

    std::vector<std::string> where;
    if (diagnostic.pin) where.push_back("pin=" + *diagnostic.pin);
    if (diagnostic.device) where.push_back("device=" + *diagnostic.device);
    if (diagnostic.connector) where.push_back("connector=" + *diagnostic.connector);
    if (!where.empty()) {
        out << "  (";
        for (std::size_t index = 0; index < where.size(); ++index) {
            if (index > 0) out << ' ';
            out << where[index];
        }
        out << ')';
    }
    out << '\n';
    if (diagnostic.hint) out << "      hint: " << *diagnostic.hint << '\n';
}

void renderBoard(std::ostream& out, const Board& board) {
    const std::vector<std::string> headers = {"pin", "gpio", "side", "capabilities", "notes"};
    std::vector<std::vector<std::string>> rows;
    for (const Pin& pin : board.pins()) {
        std::string notes;
        const auto note = [&](const char* text) {
            if (!notes.empty()) notes += ", ";
            notes += text;
        };
        if (pin.isInputOnly()) note("input-only");
        if (pin.isStrapping()) note("strapping");
        if (any(pin.capabilities & Capability::Psram)) note("psram");

        std::string capabilities;
        const auto capability = [&](Capability flag, const char* text) {
            if (!any(pin.capabilities & flag)) return;
            if (!capabilities.empty()) capabilities += ' ';
            capabilities += text;
        };
        capability(Capability::Input, "input");
        capability(Capability::Output, "output");
        capability(Capability::PullUp, "pull-up");
        capability(Capability::PullDown, "pull-down");
        capability(Capability::Adc1, "adc1");
        capability(Capability::Adc2, "adc2");
        capability(Capability::Dac, "dac");
        capability(Capability::Pwm, "pwm");
        capability(Capability::Touch, "touch");
        capability(Capability::Spi, "spi");
        capability(Capability::I2c, "i2c");
        capability(Capability::Uart, "uart");
        capability(Capability::Flash, "flash");

        rows.push_back({std::string(pin.label), pin.gpio ? std::to_string(*pin.gpio) : "-",
                        pin.side == Side::Left ? "left" : pin.side == Side::Right ? "right" : "power",
                        capabilities.empty() ? "-" : capabilities, notes});
    }

    std::vector<std::size_t> widths(headers.size());
    for (std::size_t index = 0; index < headers.size(); ++index) widths[index] = headers[index].size();
    for (const auto& row : rows) {
        for (std::size_t index = 0; index < row.size(); ++index) {
            widths[index] = std::max(widths[index], row[index].size());
        }
    }

    renderRow(out, headers, widths);
    for (std::size_t index = 0; index < widths.size(); ++index) {
        out << std::string(widths[index], '-') << (index + 1 < widths.size() ? "  " : "");
    }
    out << '\n';
    for (const auto& row : rows) renderRow(out, row, widths);

    out << "\nnot on the header:\n";
    for (const auto& [gpioNumber, reason] : board.reserved()) {
        out << "  " << gpioNumber << "  " << reason << '\n';
    }
}

void WiringPlan::render(std::ostream& out) const {
    out << name_ << "  (" << board_.name() << ", wifi=" << (wifi_ ? "on" : "off") << ")\n";
    if (!description_.empty()) out << description_ << '\n';

    if (connections_.empty()) {
        out << "(no jumpers)\n";
        return;
    }
    out << '\n';

    const std::vector<std::string> headers = {"pin", "gpio", "side", "signal", "to", "dir", "note"};
    std::vector<std::vector<std::string>> rows;
    for (const Connection& wire : connections_) {
        rows.push_back({std::string(wire.pin.label),
                        wire.pin.gpio ? std::to_string(*wire.pin.gpio) : "-",
                        wire.pin.side == Side::Left ? "left"
                                                    : wire.pin.side == Side::Right ? "right" : "power",
                        std::string(toString(wire.signal)), wire.label(),
                        std::string(toString(wire.direction)), wire.note});
    }

    std::vector<std::size_t> widths(headers.size());
    for (std::size_t index = 0; index < headers.size(); ++index) widths[index] = headers[index].size();
    for (const auto& row : rows) {
        for (std::size_t index = 0; index < row.size(); ++index) {
            widths[index] = std::max(widths[index], row[index].size());
        }
    }

    renderRow(out, headers, widths);
    for (std::size_t index = 0; index < widths.size(); ++index) {
        out << std::string(widths[index], '-') << (index + 1 < widths.size() ? "  " : "");
    }
    out << '\n';
    for (const auto& row : rows) renderRow(out, row, widths);

    const std::vector<std::string> free = freeLabels();
    out << "\nfree GPIOs: ";
    if (free.empty()) {
        out << "none";
    } else {
        for (std::size_t index = 0; index < free.size(); ++index) {
            if (index > 0) out << ", ";
            out << free[index];
        }
    }
    out << '\n';

    const std::vector<Diagnostic> findings = validate();
    out << '\n';
    if (findings.empty()) {
        out << "validation: ok, no findings\n";
        return;
    }
    std::size_t errors = 0;
    std::size_t warn = 0;
    std::size_t info = 0;
    for (const Diagnostic& finding : findings) {
        switch (finding.severity) {
            case Severity::Error: ++errors; break;
            case Severity::Warning: ++warn; break;
            case Severity::Info: ++info; break;
        }
    }
    out << "validation: " << findings.size() << " finding(s) [";
    bool first = true;
    const auto part = [&](std::size_t count, const char* label) {
        if (count == 0) return;
        if (!first) out << ", ";
        first = false;
        out << count << ' ' << label;
    };
    part(errors, "error");
    part(warn, "warning");
    part(info, "info");
    out << "]\n";
    for (const Diagnostic& finding : findings) renderDiagnostic(out, finding);
}

std::string WiringPlan::toJson() const {
    std::ostringstream out;
    out << "{\n  \"name\": \"" << escapeJson(name_) << "\",\n";
    out << "  \"board\": \"" << escapeJson(board_.name()) << "\",\n";
    out << "  \"description\": \"" << escapeJson(description_) << "\",\n";
    out << "  \"wifi\": " << (wifi_ ? "true" : "false") << ",\n";

    out << "  \"devices\": [";
    for (std::size_t index = 0; index < devices_.size(); ++index) {
        const Device& device = devices_[index];
        out << (index == 0 ? "\n" : ",\n");
        out << "    {\"name\": \"" << escapeJson(device.name) << "\", \"logic\": \""
            << toString(device.logic) << "\", \"has_pullups\": " << (device.hasPullups ? "true" : "false")
            << ", \"connectors\": [";
        for (std::size_t position = 0; position < device.connectors.size(); ++position) {
            const Connector& connector = device.connectors[position];
            out << (position == 0 ? "\n" : ",\n");
            out << "      {\"name\": \"" << escapeJson(connector.name) << "\", \"signal\": \""
                << toString(connector.signal) << "\", \"direction\": \""
                << toString(connector.resolvedDirection()) << "\"}";
        }
        if (!device.connectors.empty()) out << "\n    ";
        out << "]}";
    }
    if (!devices_.empty()) out << "\n  ";
    out << "],\n";

    out << "  \"connections\": [";
    for (std::size_t index = 0; index < connections_.size(); ++index) {
        const Connection& wire = connections_[index];
        out << (index == 0 ? "\n" : ",\n");
        out << "    {\"pin\": \"" << escapeJson(wire.pin.label) << "\", \"gpio\": "
            << (wire.pin.gpio ? std::to_string(*wire.pin.gpio) : "null") << ", \"side\": \""
            << (wire.pin.side == Side::Left ? "left" : wire.pin.side == Side::Right ? "right" : "power")
            << "\", \"signal\": \"" << toString(wire.signal) << "\", \"device\": \""
            << escapeJson(wire.device) << "\", \"connector\": \"" << escapeJson(wire.connector)
            << "\", \"direction\": \"" << toString(wire.direction) << "\", \"voltage\": \""
            << pinVoltage(wire.pin) << "\", \"note\": \"" << escapeJson(wire.note) << "\"}";
    }
    if (!connections_.empty()) out << "\n  ";
    out << "],\n";

    const std::vector<Diagnostic> findings = validate();
    out << "  \"diagnostics\": [";
    for (std::size_t index = 0; index < findings.size(); ++index) {
        const Diagnostic& finding = findings[index];
        out << (index == 0 ? "\n" : ",\n");
        out << "    {\"severity\": \"" << toString(finding.severity) << "\", \"rule\": \""
            << toString(finding.rule) << "\", \"message\": \"" << escapeJson(finding.message)
            << "\", \"pin\": " << (finding.pin ? "\"" + escapeJson(*finding.pin) + "\"" : "null")
            << ", \"device\": " << (finding.device ? "\"" + escapeJson(*finding.device) + "\"" : "null")
            << ", \"connector\": "
            << (finding.connector ? "\"" + escapeJson(*finding.connector) + "\"" : "null") << ", \"hint\": "
            << (finding.hint ? "\"" + escapeJson(*finding.hint) + "\"" : "null") << "}";
    }
    if (!findings.empty()) out << "\n  ";
    out << "]\n}";
    return out.str();
}

}  // namespace jumper
