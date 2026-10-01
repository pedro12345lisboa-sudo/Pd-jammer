// Behavioural tests for the jumper library.
//
// No external framework: every case is a function registered in the table at
// the bottom, so the suite links anywhere and reports through CTest.

#include <algorithm>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <jumper/jumper.hpp>

namespace {

int gFailures = 0;
int gChecks = 0;

void check(bool condition, const char* expression, const char* file, int line) {
    ++gChecks;
    if (condition) return;
    ++gFailures;
    std::cerr << file << ':' << line << ": FAILED  " << expression << '\n';
}

#define CHECK(expression) check((expression), #expression, __FILE__, __LINE__)

#define CHECK_EQ(actual, expected)                                                              \
    do {                                                                                        \
        const auto actualValue = (actual);                                                      \
        const auto expectedValue = (expected);                                                  \
        if (!(actualValue == expectedValue)) {                                                  \
            ++gFailures;                                                                        \
            std::cerr << __FILE__ << ':' << __LINE__ << ": FAILED  " << #actual << " == "        \
                      << #expected << "  (got " << actualValue << ", want " << expectedValue     \
                      << ")\n";                                                                 \
        }                                                                                       \
        ++gChecks;                                                                              \
    } while (false)

#define CHECK_THROWS(expression, ExceptionType)                                                \
    do {                                                                                        \
        bool caught = false;                                                                    \
        try {                                                                                   \
            (void)(expression);                                                                 \
        } catch (const ExceptionType&) {                                                        \
            caught = true;                                                                      \
        } catch (...) {                                                                         \
        }                                                                                       \
        check(caught, #expression " throws " #ExceptionType, __FILE__, __LINE__);              \
    } while (false)

using jumper::Capability;
using jumper::Connector;
using jumper::Device;
using jumper::Diagnostic;
using jumper::Direction;
using jumper::LogicLevel;
using jumper::Pin;
using jumper::Rule;
using jumper::Severity;
using jumper::Side;
using jumper::Signal;
using jumper::WiringPlan;

bool hasRule(const std::vector<Diagnostic>& findings, Rule rule) {
    return std::any_of(findings.begin(), findings.end(),
                       [rule](const Diagnostic& d) { return d.rule == rule; });
}

std::size_t countRule(const std::vector<Diagnostic>& findings, Rule rule) {
    return static_cast<std::size_t>(
        std::count_if(findings.begin(), findings.end(),
                      [rule](const Diagnostic& d) { return d.rule == rule; }));
}

Device i2cDevice(std::string name = "BME280", bool hasPullups = false) {
    Device device;
    device.name = std::move(name);
    device.logic = LogicLevel::ThreeV3;
    device.connectors = {{"SDA", Signal::I2cSda}, {"SCL", Signal::I2cScl}};
    device.hasPullups = hasPullups;
    return device;
}

WiringPlan validPlan() {
    WiringPlan plan{"Weather station"};
    plan.addDevice(i2cDevice("BME280", true));
    plan.wire("BME280", "SDA", "D21");
    plan.wire("BME280", "SCL", "D22");
    return plan;
}

std::string render(const WiringPlan& plan) {
    std::ostringstream out;
    plan.render(out);
    return out.str();
}

// ---------------------------------------------------------------------------

void testBoardTable() {
    const jumper::Board& board = jumper::Board::devkitV1();
    CHECK_EQ(board.pins().size(), 30u);

    const std::size_t left = static_cast<std::size_t>(
        std::count_if(board.pins().begin(), board.pins().end(),
                      [](const Pin& pin) { return pin.side == Side::Left; }));
    const std::size_t right = static_cast<std::size_t>(
        std::count_if(board.pins().begin(), board.pins().end(),
                      [](const Pin& pin) { return pin.side == Side::Right; }));
    CHECK_EQ(left, 13u);
    CHECK_EQ(right, 13u);

    CHECK_EQ(board.groundLabels().size(), 2u);
    CHECK_EQ(board.lookup("d21").gpio.value(), 21);
    CHECK_EQ(board.lookup("SDA").label, "D21");
    CHECK_EQ(board.lookup("scl").label, "D22");
    CHECK_EQ(board.lookup("5V").label, "VIN");
    CHECK(board.find("banana") == nullptr);
    CHECK_THROWS(board.lookup("banana"), jumper::UnknownPin);
    CHECK_THROWS(board.lookup("D2O"), jumper::UnknownPin);

    std::vector<int> gpios;
    for (const Pin& pin : board.pins()) {
        if (pin.gpio) gpios.push_back(*pin.gpio);
    }
    std::vector<int> sorted = gpios;
    std::sort(sorted.begin(), sorted.end());
    CHECK(std::adjacent_find(sorted.begin(), sorted.end()) == sorted.end());

    std::vector<std::string> inputOnly;
    std::vector<int> strapping;
    std::vector<int> adc1;
    std::vector<int> adc2;
    for (const Pin& pin : board.pins()) {
        if (pin.isInputOnly()) inputOnly.emplace_back(pin.label);
        if (pin.isStrapping()) strapping.push_back(*pin.gpio);
        if (jumper::any(pin.capabilities & Capability::Adc1)) adc1.push_back(*pin.gpio);
        if (jumper::any(pin.capabilities & Capability::Adc2)) adc2.push_back(*pin.gpio);
    }
    CHECK_EQ(inputOnly.size(), 4u);
    CHECK_EQ(strapping.size(), 4u);
    CHECK_EQ(adc1.size(), 6u);
    CHECK_EQ(adc2.size(), 9u);
    CHECK(jumper::any(board.lookup("D15").capabilities & Capability::Psram));

    CHECK(board.rail(LogicLevel::ThreeV3).label == "3V3");
    CHECK(board.rail(LogicLevel::FiveV).label == "VIN");
    CHECK(board.rail(LogicLevel::ThreeV3, true).isGround());
    CHECK_EQ(board.reserved().size(), 7u);

    CHECK(!board.lookup("D34").supports(Direction::Output));
    CHECK(board.lookup("D34").supports(Direction::Input));
    CHECK(!board.lookup("D34").supports(Direction::Bidirectional));
    CHECK(board.lookup("D21").supports(Direction::Bidirectional));
    CHECK(board.lookup("D21").supports(Direction::Output));
}

void testHappyPath() {
    const WiringPlan plan = validPlan();
    CHECK(plan.isValid());
    CHECK(plan.errors().empty());
    (void)plan.assertValid();  // must not throw

    CHECK_EQ(plan.connections().size(), 4u);
    const std::string table = render(plan);
    CHECK(table.find("Weather station") != std::string::npos);
    CHECK(table.find("BME280.SDA") != std::string::npos);
    CHECK(table.find("validation:") != std::string::npos);

    const std::vector<std::string> free = plan.freeLabels();
    CHECK(std::find(free.begin(), free.end(), "D21") == free.end());
    CHECK(std::find(free.begin(), free.end(), "D34") == free.end());
    CHECK(std::find(free.begin(), free.end(), "D25") != free.end());
    CHECK(std::find(plan.freeLabels(true).begin(), plan.freeLabels(true).end(), "D34") !=
          plan.freeLabels(true).end());
}

void testGroundIsDistributedOverBothPins() {
    WiringPlan plan{"Two modules"};
    plan.addDevice(i2cDevice("BME280", true));
    Device led;
    led.name = "LED";
    led.connectors = {{"anode", Signal::GpioOut}};
    plan.addDevice(led);

    int groundCount = 0;
    for (const jumper::Connection& wire : plan.connections()) {
        if (wire.isGround()) ++groundCount;
    }
    CHECK(groundCount == 2);
    CHECK(plan.isValid());
}

void testSharedPowerRailIsNotAnError() {
    WiringPlan plan{"Two modules"};
    plan.addDevice(i2cDevice("BME280", true));
    Device led;
    led.name = "LED";
    led.connectors = {{"anode", Signal::GpioOut}};
    plan.addDevice(led);
    plan.wire("LED", "anode", "D23");

    CHECK(!hasRule(plan.validate(), Rule::PinAlreadyUsed));
    CHECK(hasRule(plan.validate(), Rule::PowerRailShared));
    CHECK(plan.isValid());
}

void testProgrammingErrors() {
    WiringPlan plan{"p"};
    CHECK_THROWS(plan.connect("D99", Signal::GpioOut, "X", "Y"), jumper::UnknownPin);
    CHECK_THROWS(plan.wire("ghost", "SDA", "D21"), jumper::UnknownConnector);

    plan.addDevice(i2cDevice());
    CHECK_THROWS(plan.wire("BME280", "SDA_WRONG", "D21"), jumper::UnknownConnector);
    CHECK_THROWS(plan.addDevice(i2cDevice()), jumper::DuplicateDevice);
}

void testPinCapabilityRules() {
    {
        WiringPlan plan{"p"};
        Device relay;
        relay.name = "RELAY";
        relay.connectors = {{"IN", Signal::GpioIn}};
        plan.addDevice(relay);
        plan.connect("D34", Signal::GpioOut, "RELAY", "IN");
        const std::vector<Diagnostic> findings = plan.validate();
        CHECK_EQ(countRule(findings, Rule::PinInputOnly), 1u);
        CHECK(hasRule(findings, Rule::PinAlreadyUsed) == false);
        CHECK(!plan.isValid());
    }
    {
        WiringPlan plan{"p"};
        plan.connect("D21", Signal::Ground, "MODULE", "GND");
        CHECK(hasRule(plan.validate(), Rule::PinInputOnly));
    }
    {
        WiringPlan plan{"p"};
        plan.connect("D21", Signal::Power3v3, "MODULE", "VCC");
        CHECK(hasRule(plan.validate(), Rule::PinInputOnly));
    }
    {
        WiringPlan plan{"p"};
        plan.addDevice(i2cDevice("BME280", true));
        plan.wire("BME280", "SDA", "D21");
        plan.wire("BME280", "SCL", "D21");
        CHECK(hasRule(plan.validate(), Rule::PinAlreadyUsed));
    }
    {
        WiringPlan plan{"p"};
        Device spi;
        spi.name = "SD";
        spi.connectors = {{"CS", Signal::SpiCs}};
        spi.needsPower = false;
        plan.addDevice(spi);
        plan.wire("SD", "CS", "D5");
        const std::vector<Diagnostic> findings = plan.validate();
        CHECK(hasRule(findings, Rule::PinStrapping));
        CHECK(plan.isValid());
    }
    {
        WiringPlan plan{"p"};
        Device gps;
        gps.name = "GPS";
        gps.connectors = {{"TX", Signal::UartTx}};
        gps.needsPower = false;
        plan.addDevice(gps);
        plan.wire("GPS", "TX", "TX0");
        CHECK(hasRule(plan.validate(), Rule::PinUart0));

        WiringPlan alt{"p"};
        alt.addDevice(gps);
        alt.wire("GPS", "TX", "TX2");
        CHECK(!hasRule(alt.validate(), Rule::PinUart0));
    }
    {
        WiringPlan plan{"p"};
        Device screen;
        screen.name = "TFT";
        screen.connectors = {{"DC", Signal::GpioOut}};
        screen.needsPower = false;
        plan.addDevice(screen);
        plan.wire("TFT", "DC", "D15");
        CHECK(hasRule(plan.validate(), Rule::PinPsram));
    }
}

void testAnalogRules() {
    {
        WiringPlan plan{"p"};
        plan.enableWifi();
        Device pot;
        pot.name = "POT";
        pot.connectors = {{"wiper", Signal::AdcRead}};
        pot.needsPower = false;
        plan.addDevice(pot);
        plan.wire("POT", "wiper", "D25");
        const std::vector<Diagnostic> findings = plan.validate();
        CHECK_EQ(countRule(findings, Rule::Adc2WithWifi), 1u);
        CHECK(!plan.isValid());
    }
    {
        WiringPlan plan{"p"};
        Device pot;
        pot.name = "POT";
        pot.connectors = {{"wiper", Signal::AdcRead}};
        pot.needsPower = false;
        plan.addDevice(pot);
        plan.wire("POT", "wiper", "D25");
        CHECK(!hasRule(plan.validate(), Rule::Adc2WithWifi));
    }
    {
        WiringPlan plan{"p", jumper::Board::devkitV1()};
        plan.enableWifi();
        Device pot;
        pot.name = "POT";
        pot.connectors = {{"wiper", Signal::AdcRead}};
        pot.needsPower = false;
        plan.addDevice(pot);
        plan.wire("POT", "wiper", "D32");
        CHECK(!hasRule(plan.validate(), Rule::Adc2WithWifi));
        CHECK(plan.isValid());
    }
    {
        WiringPlan plan{"p"};
        Device button;
        button.name = "BUTTON";
        button.connectors = {{"leg", Signal::ButtonIn}};
        button.needsPower = false;
        plan.addDevice(button);
        plan.wire("BUTTON", "leg", "D35");
        const std::vector<Diagnostic> findings = plan.validate();
        CHECK_EQ(countRule(findings, Rule::NoInternalPullup), 1u);
    }
}

void testPowerRules() {
    {
        WiringPlan plan{"p"};
        plan.addDevice(i2cDevice("BME280", true), false);
        plan.wire("BME280", "SDA", "D21");
        plan.wire("BME280", "SCL", "D22");
        const std::vector<Diagnostic> findings = plan.validate();
        CHECK(hasRule(findings, Rule::PowerMissing));
        CHECK(hasRule(findings, Rule::GroundMissing));
    }
    {
        WiringPlan plan{"p"};
        plan.connect("VIN", Signal::Power3v3, "MODULE", "VCC");
        CHECK(hasRule(plan.validate(), Rule::PowerConflict));
    }
    {
        WiringPlan plan{"p"};
        Device relay;
        relay.name = "RELAY";
        relay.logic = LogicLevel::FiveV;
        relay.connectors = {{"IN", Signal::GpioIn}};
        plan.addDevice(relay);
        bool fedFromVin = false;
        for (const jumper::Connection& wire : plan.connections()) {
            if (wire.isPower()) fedFromVin = wire.pin.label == "VIN";
        }
        CHECK(fedFromVin);
    }
}

void testLevelRules() {
    {
        WiringPlan plan{"p"};
        Device sonar;
        sonar.name = "HC-SR04";
        sonar.logic = LogicLevel::FiveV;
        sonar.connectors = {{"echo", Signal::SensorIn, std::nullopt, std::nullopt, LogicLevel::FiveV}};
        plan.addDevice(sonar);
        plan.wire("HC-SR04", "echo", "D34");
        const std::vector<Diagnostic> findings = plan.validate();
        CHECK_EQ(countRule(findings, Rule::LevelMismatch), 1u);
        CHECK(!plan.isValid());
    }
    {
        WiringPlan plan{"p"};
        Device sonar;
        sonar.name = "HC-SR04";
        sonar.logic = LogicLevel::FiveV;
        sonar.connectors = {{"trig", Signal::TriggerOut}};
        plan.addDevice(sonar);
        plan.wire("HC-SR04", "trig", "TX2");
        const std::vector<Diagnostic> findings = plan.validate();
        CHECK_EQ(countRule(findings, Rule::LevelMargin), 1u);
        CHECK(plan.isValid());
    }
    {
        WiringPlan plan{"p"};
        Device sonar;
        sonar.name = "HC-SR04";
        sonar.logic = LogicLevel::FiveV;
        sonar.connectors = {{"trig", Signal::TriggerOut, std::nullopt, std::nullopt, LogicLevel::ThreeV3}};
        plan.addDevice(sonar);
        plan.wire("HC-SR04", "trig", "TX2");
        CHECK(!hasRule(plan.validate(), Rule::LevelMargin));
    }
}

void testCoverageAndPullups() {
    {
        WiringPlan plan{"p"};
        plan.addDevice(i2cDevice());
        plan.wire("BME280", "SDA", "D21");
        plan.wire("BME280", "SCL", "D22");
        const std::vector<Diagnostic> findings = plan.validate();
        CHECK_EQ(countRule(findings, Rule::InternalI2c), 2u);
        CHECK(plan.isValid());
    }
    {
        WiringPlan plan{"p"};
        plan.addDevice(i2cDevice("BME280", true));
        plan.wire("BME280", "SDA", "D21");
        CHECK(hasRule(plan.validate(), Rule::ConnectorUnused));
    }
}

void testOrderingAndJson() {
    WiringPlan plan{"p"};
    Device relay;
    relay.name = "RELAY";
    relay.connectors = {{"a", Signal::GpioOut}, {"b", Signal::GpioOut}};
    plan.addDevice(relay);
    plan.wire("RELAY", "a", "D34");
    plan.wire("RELAY", "b", "D5");

    const std::vector<Diagnostic> findings = plan.validate();
    for (std::size_t index = 1; index < findings.size(); ++index) {
        CHECK(jumper::rank(findings[index - 1].severity) >= jumper::rank(findings[index].severity));
    }

    const WiringPlan good = validPlan();
    const std::string json = good.toJson();
    CHECK(json.find("\"name\": \"Weather station\"") != std::string::npos);
    CHECK(json.find("\"signal\": \"I2C_SDA\"") != std::string::npos);
    CHECK(json.find("\"diagnostics\": []") != std::string::npos);
    CHECK(!good.toJson().empty());
}

void testRenderBoard() {
    std::ostringstream out;
    jumper::renderBoard(out, jumper::Board::devkitV1());
    const std::string text = out.str();
    CHECK(text.find("D21") != std::string::npos);
    CHECK(text.find("input-only") != std::string::npos);
    CHECK(text.find("strapping") != std::string::npos);
    CHECK(text.find("GPIO0") != std::string::npos);
}

struct TestCase {
    const char* name;
    void (*run)();
};

}  // namespace

int main() {
    const TestCase cases[] = {
        {"board table", testBoardTable},
        {"happy path", testHappyPath},
        {"ground distribution", testGroundIsDistributedOverBothPins},
        {"shared power rail", testSharedPowerRailIsNotAnError},
        {"programming errors", testProgrammingErrors},
        {"pin capability rules", testPinCapabilityRules},
        {"analog rules", testAnalogRules},
        {"power rules", testPowerRules},
        {"level rules", testLevelRules},
        {"coverage and pull-ups", testCoverageAndPullups},
        {"ordering and json", testOrderingAndJson},
        {"render board", testRenderBoard},
    };

    for (const TestCase& test : cases) {
        const int before = gFailures;
        test.run();
        std::cout << (gFailures == before ? "  ok   " : "  FAIL ") << test.name << '\n';
    }

    std::cout << (gFailures == 0 ? "PASS " : "FAIL ") << (gChecks - gFailures) << '/' << gChecks
              << " checks\n";
    return gFailures == 0 ? 0 : 1;
}
