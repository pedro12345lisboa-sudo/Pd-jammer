// jumper - wiring plans for the ESP32 DevKit V1.
//
// Describe the board and the peripherals, let the library work out which
// jumpers exist, and get a table plus a list of wiring mistakes back.
//
//   #include <jumper/jumper.hpp>
//
//   int main() {
//     jumper::WiringPlan plan{"Weather station"};
//     plan.addDevice({"BME280", jumper::LogicLevel::ThreeV3, {
//                        {"SDA", jumper::Signal::I2cSda},
//                        {"SCL", jumper::Signal::I2cScl}}, true, true, true});
//     plan.wire("BME280", "SDA", "D21");
//     plan.wire("BME280", "SCL", "D22");
//     plan.enableWifi();
//     plan.assertValid();               // throws jumper::WiringInvalid
//     plan.render(std::cout);
//   }
//
// The rules, identifiers and severities mirror the Python implementation of
// the same library, so a plan validated on the host is the plan you wire on
// the bench.

#ifndef JUMPER_JUMPER_HPP
#define JUMPER_JUMPER_HPP

#include <cstdint>
#include <exception>
#include <iosfwd>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace jumper {

// ---------------------------------------------------------------------------
// Enumerations
// ---------------------------------------------------------------------------

/// Physical side of the development board header.
enum class Side { Left, Right, Power };

/// Who drives the electrical line.
enum class Direction {
    Output,         ///< The MCU sources current.
    Input,          ///< The peripheral sources current.
    Bidirectional,  ///< Both sides drive, as on an open-drain bus.
    Supply,         ///< A power rail feeding a peripheral.
    Return,         ///< A ground return path.
};

constexpr bool isData(Direction direction) noexcept {
    return direction != Direction::Supply && direction != Direction::Return;
}

constexpr std::string_view toString(Direction direction) noexcept {
    switch (direction) {
        case Direction::Output: return "output";
        case Direction::Input: return "input";
        case Direction::Bidirectional: return "bidirectional";
        case Direction::Supply: return "supply";
        case Direction::Return: return "return";
    }
    return "?";
}

/// Voltage domain a peripheral speaks.
enum class LogicLevel { ThreeV3, FiveV };

constexpr std::string_view toString(LogicLevel level) noexcept {
    return level == LogicLevel::ThreeV3 ? "3.3V" : "5V";
}

/// Semantic role of a jumper wire.
enum class Signal {
    Ground,
    Power3v3,
    Power5v,
    I2cSda,
    I2cScl,
    SpiSck,
    SpiMosi,
    SpiMiso,
    SpiCs,
    UartTx,
    UartRx,
    GpioOut,
    GpioIn,
    PwmOut,
    AdcRead,
    TriggerOut,
    SensorIn,
    ButtonIn,
    Other,
};

/// The direction a signal implies when nothing else is declared.
constexpr Direction defaultDirection(Signal signal) noexcept {
    switch (signal) {
        case Signal::Ground: return Direction::Return;
        case Signal::Power3v3:
        case Signal::Power5v: return Direction::Supply;
        case Signal::I2cSda:
        case Signal::I2cScl:
        case Signal::Other: return Direction::Bidirectional;
        case Signal::SpiSck:
        case Signal::SpiMosi:
        case Signal::SpiCs:
        case Signal::UartTx:
        case Signal::GpioOut:
        case Signal::PwmOut:
        case Signal::TriggerOut: return Direction::Output;
        case Signal::SpiMiso:
        case Signal::UartRx:
        case Signal::GpioIn:
        case Signal::AdcRead:
        case Signal::SensorIn:
        case Signal::ButtonIn: return Direction::Input;
    }
    return Direction::Bidirectional;
}

/// The logic voltage a signal carries, empty when not applicable.
constexpr std::optional<LogicLevel> signalVoltage(Signal signal) noexcept {
    switch (signal) {
        case Signal::Power3v3: return LogicLevel::ThreeV3;
        case Signal::Power5v: return LogicLevel::FiveV;
        case Signal::I2cSda:
        case Signal::I2cScl:
        case Signal::SpiSck:
        case Signal::SpiMosi:
        case Signal::SpiCs:
        case Signal::UartTx:
        case Signal::UartRx:
        case Signal::GpioOut:
        case Signal::GpioIn:
        case Signal::PwmOut:
        case Signal::AdcRead:
        case Signal::TriggerOut:
        case Signal::SensorIn:
        case Signal::ButtonIn: return LogicLevel::ThreeV3;
        case Signal::Ground:
        case Signal::SpiMiso:
        case Signal::Other: return std::nullopt;
    }
    return std::nullopt;
}

/// True for signals that need a pull-up to be readable.
constexpr bool needsPullup(Signal signal) noexcept {
    return signal == Signal::I2cSda || signal == Signal::I2cScl || signal == Signal::ButtonIn;
}

constexpr std::string_view toString(Signal signal) noexcept {
    switch (signal) {
        case Signal::Ground: return "GND";
        case Signal::Power3v3: return "3V3";
        case Signal::Power5v: return "5V";
        case Signal::I2cSda: return "I2C_SDA";
        case Signal::I2cScl: return "I2C_SCL";
        case Signal::SpiSck: return "SPI_SCK";
        case Signal::SpiMosi: return "SPI_MOSI";
        case Signal::SpiMiso: return "SPI_MISO";
        case Signal::SpiCs: return "SPI_CS";
        case Signal::UartTx: return "UART_TX";
        case Signal::UartRx: return "UART_RX";
        case Signal::GpioOut: return "GPIO_OUT";
        case Signal::GpioIn: return "GPIO_IN";
        case Signal::PwmOut: return "PWM_OUT";
        case Signal::AdcRead: return "ADC_READ";
        case Signal::TriggerOut: return "TRIGGER_OUT";
        case Signal::SensorIn: return "SENSOR_IN";
        case Signal::ButtonIn: return "BUTTON_IN";
        case Signal::Other: return "OTHER";
    }
    return "?";
}

/// Peripheral capabilities of a single GPIO. Values mirror the Python
/// ``jumper.Capability`` IntFlag.
enum class Capability : std::uint32_t {
    None = 0,
    Input = 1u << 0,
    Output = 1u << 1,
    PullUp = 1u << 2,
    PullDown = 1u << 3,
    Adc1 = 1u << 4,
    Adc2 = 1u << 5,
    Dac = 1u << 6,
    Pwm = 1u << 7,
    Touch = 1u << 8,
    Spi = 1u << 9,
    I2c = 1u << 10,
    Uart = 1u << 11,
    InputOnly = 1u << 12,
    Flash = 1u << 13,
    Strapping = 1u << 14,
    Psram = 1u << 15,
};

constexpr Capability operator|(Capability lhs, Capability rhs) noexcept {
    return static_cast<Capability>(static_cast<std::uint32_t>(lhs) |
                                   static_cast<std::uint32_t>(rhs));
}

constexpr Capability operator&(Capability lhs, Capability rhs) noexcept {
    return static_cast<Capability>(static_cast<std::uint32_t>(lhs) &
                                   static_cast<std::uint32_t>(rhs));
}

constexpr bool any(Capability value) noexcept {
    return static_cast<std::uint32_t>(value) != 0u;
}

/// How much a finding matters.
enum class Severity { Info, Warning, Error };

constexpr int rank(Severity severity) noexcept {
    switch (severity) {
        case Severity::Info: return 0;
        case Severity::Warning: return 1;
        case Severity::Error: return 2;
    }
    return 0;
}

constexpr std::string_view toString(Severity severity) noexcept {
    switch (severity) {
        case Severity::Info: return "info";
        case Severity::Warning: return "warning";
        case Severity::Error: return "error";
    }
    return "?";
}

/// Stable identifiers, usable as CI suppression keys. Identical strings to the
/// Python ``jumper.Rule`` values.
enum class Rule {
    PinInputOnly,
    PinStrapping,
    PinUart0,
    PinPsram,
    PinAlreadyUsed,
    NoInternalPullup,
    Adc2WithWifi,
    PowerConflict,
    PowerMissing,
    GroundMissing,
    GroundDuplicated,
    PowerRailShared,
    LevelMismatch,
    LevelMargin,
    ConnectorUnused,
    DeviceUnwired,
    InternalI2c,
};

constexpr std::string_view toString(Rule rule) noexcept {
    switch (rule) {
        case Rule::PinInputOnly: return "pin/input-only";
        case Rule::PinStrapping: return "pin/strapping";
        case Rule::PinUart0: return "pin/uart0";
        case Rule::PinPsram: return "pin/psram";
        case Rule::PinAlreadyUsed: return "pin/already-used";
        case Rule::NoInternalPullup: return "pin/no-internal-pullup";
        case Rule::Adc2WithWifi: return "adc/adc2-with-wifi";
        case Rule::PowerConflict: return "power/multiple-sources";
        case Rule::PowerMissing: return "power/peripheral-not-powered";
        case Rule::GroundMissing: return "power/peripheral-without-ground";
        case Rule::GroundDuplicated: return "power/duplicate-ground";
        case Rule::PowerRailShared: return "power/shared-rail";
        case Rule::LevelMismatch: return "power/level-mismatch";
        case Rule::LevelMargin: return "power/insufficient-level";
        case Rule::ConnectorUnused: return "device/connector-unused";
        case Rule::DeviceUnwired: return "device/not-wired";
        case Rule::InternalI2c: return "bus/internal-pullups-absent";
    }
    return "?";
}

struct Diagnostic;

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// Base class for every error raised by this library.
class Error : public std::exception {
public:
    explicit Error(std::string message) : message_(std::move(message)) {}
    [[nodiscard]] const char* what() const noexcept override { return message_.c_str(); }

private:
    std::string message_;
};

/// Thrown when a board label cannot be resolved.
class UnknownPin : public Error {
public:
    UnknownPin(std::string label, std::optional<std::string> suggestion);
    [[nodiscard]] const std::string& label() const noexcept { return label_; }
    [[nodiscard]] const std::optional<std::string>& suggestion() const noexcept { return suggestion_; }

private:
    std::string label_;
    std::optional<std::string> suggestion_;
};

/// Thrown when a peripheral contact cannot be resolved.
class UnknownConnector : public Error {
public:
    UnknownConnector(std::string device, std::string connector, std::string available);
};

/// Thrown when the same peripheral name is registered twice.
class DuplicateDevice : public Error {
public:
    explicit DuplicateDevice(const std::string& name);
};

/// Thrown by ``WiringPlan::assertValid`` when errors are present.
class WiringInvalid : public Error {
public:
    WiringInvalid(std::vector<Diagnostic> diagnostics, std::string message);
    [[nodiscard]] const std::vector<Diagnostic>& diagnostics() const noexcept { return diagnostics_; }

private:
    std::vector<Diagnostic> diagnostics_;
};

// ---------------------------------------------------------------------------
// Board
// ---------------------------------------------------------------------------

/// A single break-out header contact.
struct Pin {
    std::string_view label;
    std::optional<int> gpio;
    Side side{Side::Power};
    Capability capabilities{Capability::None};
    std::string_view aliases;
    int slot{-1};

    [[nodiscard]] bool isPower() const noexcept { return side == Side::Power; }
    [[nodiscard]] bool isGround() const noexcept { return label == "GND"; }
    [[nodiscard]] bool isInputOnly() const noexcept {
        return any(capabilities & Capability::InputOnly);
    }
    [[nodiscard]] bool isStrapping() const noexcept {
        return any(capabilities & Capability::Strapping);
    }
    [[nodiscard]] bool hasInternalPullup() const noexcept {
        return any(capabilities & Capability::PullUp);
    }
    [[nodiscard]] std::optional<LogicLevel> voltage() const noexcept;
    [[nodiscard]] bool supports(Direction direction) const noexcept;
    [[nodiscard]] bool matches(std::string_view key) const noexcept;
};

/// An immutable, self-checked pin table.
class Board {
public:
    /// DOIT ESP32 DEVKIT V1, 30-pin version.
    [[nodiscard]] static const Board& devkitV1();

    [[nodiscard]] std::string_view name() const noexcept { return name_; }
    [[nodiscard]] const std::vector<Pin>& pins() const noexcept { return pins_; }

    /// GPIO numbers that are not exposed on the header.
    [[nodiscard]] const std::vector<std::pair<std::string, std::string>>& reserved() const noexcept {
        return reserved_;
    }

    /// Every ground contact; the DevKit V1 exposes two.
    [[nodiscard]] std::vector<std::string> groundLabels() const;
    [[nodiscard]] std::vector<const Pin*> groundPins() const;

    /// Resolve a label, case-insensitively, aliases accepted.
    /// \throws UnknownPin
    [[nodiscard]] const Pin& lookup(std::string_view label) const;

    /// Non-raising lookup.
    [[nodiscard]] const Pin* find(std::string_view label) const noexcept;

    /// Power rail for a voltage, or the first ground contact.
    [[nodiscard]] const Pin& rail(LogicLevel level, bool ground = false) const;

private:
    Board(std::string name, std::vector<Pin> pins,
          std::vector<std::pair<std::string, std::string>> reserved);

    void selfCheck() const;

    std::string name_;
    std::vector<Pin> pins_;
    std::vector<std::pair<std::string, std::string>> reserved_;
};

// ---------------------------------------------------------------------------
// Peripherals
// ---------------------------------------------------------------------------

/// A labelled contact on a peripheral.
struct Connector {
    std::string name;
    Signal signal{Signal::Other};
    std::optional<Direction> direction{};
    std::optional<bool> requiresPullup{};
    /// Overrides the voltage implied by the signal; set it for 5 V parts whose
    /// logic inputs tolerate 3.3 V (HC-SR04 trigger, most relay boards).
    std::optional<LogicLevel> voltage{};

    [[nodiscard]] Direction resolvedDirection() const noexcept {
        return direction.value_or(defaultDirection(signal));
    }
    [[nodiscard]] bool resolvedPullup() const noexcept {
        return requiresPullup.value_or(needsPullup(signal));
    }
    [[nodiscard]] std::optional<LogicLevel> resolvedVoltage() const noexcept {
        return voltage ? voltage : signalVoltage(signal);
    }
};

/// A peripheral wired to the board.
struct Device {
    std::string name;
    LogicLevel logic{LogicLevel::ThreeV3};
    std::vector<Connector> connectors{};
    bool needsPower{true};
    bool needsGround{true};
    bool hasPullups{false};
    std::string notes{};

    /// \throws UnknownConnector
    [[nodiscard]] const Connector& connector(const std::string& name) const;
};

// ---------------------------------------------------------------------------
// Wiring plan
// ---------------------------------------------------------------------------

/// One physical jumper wire.
struct Connection {
    Pin pin;
    Signal signal{Signal::Other};
    std::string device;
    std::string connector;
    Direction direction{Direction::Bidirectional};
    std::string note;
    std::optional<LogicLevel> declaredVoltage{};

    [[nodiscard]] bool isPower() const noexcept { return direction == Direction::Supply; }
    [[nodiscard]] bool isGround() const noexcept { return direction == Direction::Return; }
    [[nodiscard]] bool isData() const noexcept { return jumper::isData(direction); }
    [[nodiscard]] std::optional<LogicLevel> voltage() const noexcept {
        return declaredVoltage ? declaredVoltage : signalVoltage(signal);
    }
    [[nodiscard]] std::string label() const { return device + "." + connector; }
};

/// A single finding about a wiring plan.
struct Diagnostic {
    Severity severity{Severity::Info};
    Rule rule{Rule::ConnectorUnused};
    std::string message;
    std::optional<std::string> pin;
    std::optional<std::string> device;
    std::optional<std::string> connector;
    std::optional<std::string> hint;
};

/// A board, the peripherals on it, and the wires between them.
class WiringPlan {
public:
    explicit WiringPlan(std::string name, const Board& board = Board::devkitV1());

    [[nodiscard]] const std::string& name() const noexcept { return name_; }
    [[nodiscard]] const std::string& description() const noexcept { return description_; }
    void setDescription(std::string value) { description_ = std::move(value); }

    [[nodiscard]] bool wifi() const noexcept { return wifi_; }
    WiringPlan& enableWifi(bool enabled = true) noexcept;

    /// Register a peripheral, optionally wiring its power and ground.
    /// \throws DuplicateDevice
    WiringPlan& addDevice(Device device, bool autoPower = true);

    /// Add a jumper wire; the low-level escape hatch. \throws UnknownPin
    WiringPlan& connect(std::string_view pin, Signal signal, std::string device,
                        std::string connector, std::optional<Direction> direction = std::nullopt,
                        std::optional<LogicLevel> voltage = std::nullopt, std::string note = "");
    WiringPlan& connect(const Pin& pin, Signal signal, std::string device,
                        std::string connector, std::optional<Direction> direction = std::nullopt,
                        std::optional<LogicLevel> voltage = std::nullopt, std::string note = "");

    /// Wire a declared peripheral contact to a board pin.
    /// \throws UnknownConnector, UnknownPin
    WiringPlan& wire(const std::string& device, const std::string& connector,
                     std::string_view pin, std::string note = "");

    [[nodiscard]] const std::vector<Device>& devices() const noexcept { return devices_; }
    [[nodiscard]] const std::vector<Connection>& connections() const noexcept { return connections_; }

    /// Board labels still free; power rails and input-only contacts excluded.
    [[nodiscard]] std::vector<std::string> freeLabels(bool includeInputOnly = false) const;

    /// Run every rule; findings come back most severe first.
    [[nodiscard]] std::vector<Diagnostic> validate() const;

    [[nodiscard]] std::vector<Diagnostic> errors() const;
    [[nodiscard]] std::vector<Diagnostic> warnings() const;
    [[nodiscard]] bool isValid() const { return errors().empty(); }

    /// \throws WiringInvalid
    const WiringPlan& assertValid() const;

    /// Human-readable wiring table plus the validation summary.
    void render(std::ostream& out) const;

    /// Machine-readable export, same shape as the Python ``plan_to_dict``.
    [[nodiscard]] std::string toJson() const;

private:
    const Pin& nextGroundPin();

    void checkPinCapabilities(std::vector<Diagnostic>& out) const;
    void checkSingleUse(std::vector<Diagnostic>& out) const;
    void checkGroundAndPower(std::vector<Diagnostic>& out) const;
    void checkLevels(std::vector<Diagnostic>& out) const;
    void checkAnalog(std::vector<Diagnostic>& out) const;
    void checkCoverage(std::vector<Diagnostic>& out) const;

    const Device* findDevice(const std::string& name) const noexcept;

    std::string name_;
    std::string description_;
    const Board& board_;
    bool wifi_{false};
    std::vector<Device> devices_;
    std::vector<Connection> connections_;
    std::size_t groundCursor_{0};
};

/// Print a diagnostic the way the Python renderer does.
void renderDiagnostic(std::ostream& out, const Diagnostic& diagnostic);

/// Print the full pinout of a board.
void renderBoard(std::ostream& out, const Board& board);

}  // namespace jumper

#endif  // JUMPER_JUMPER_HPP
