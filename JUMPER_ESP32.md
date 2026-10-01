# Jumpers e Pinagem — ESP32 DevKit V1 (30 pinos)

Guia de referência para ligar o ESP32 em protoboard com fios jumper.

## 1. Pinagem da placa (lado a lado, USB em cima)

**Lado esquerdo** (GPIO + alimentação):

| Pos | Rótulo | GPIO | Uso |
|---|---|---|---|
| 1 | EN | – | Reset (habilita o chip) |
| 2 | VP | 36 | Entrada **somente** |
| 3 | VN | 39 | Entrada **somente** |
| 4 | D34 | 34 | Entrada **somente** |
| 5 | D35 | 35 | Entrada **somente** |
| 6 | D32 | 32 | ADC1 ch4 / TOUCH |
| 7 | D33 | 33 | ADC1 ch5 / TOUCH |
| 8 | D25 | 25 | DAC1 / ADC2 |
| 9 | D26 | 26 | DAC2 / ADC2 |
| 10 | D27 | 27 | ADC2 / TOUCH |
| 11 | D14 | 14 | PWM, TOUCH |
| 12 | D13 | 13 | PWM, TOUCH |
| 13 | D12 | 12 | ⚠ strapping — evite |
| 14 | GND | – | Terra |
| 15 | VIN | – | 5 V de entrada |

**Lado direito**:

| Pos | Rótulo | GPIO | Uso |
|---|---|---|---|
| 1 | D23 | 23 | SPI MOSI |
| 2 | D22 | 22 | I2C SCL |
| 3 | TX0 | 1 | UART0 TX (não usar no boot) |
| 4 | RX0 | 3 | UART0 RX (não usar no boot) |
| 5 | D21 | 21 | I2C SDA |
| 6 | D19 | 19 | SPI MISO |
| 7 | D18 | 18 | SPI SCK |
| 8 | D5 | 5 | SPI CS / PWM / strapping |
| 9 | TX2 | 17 | UART2 TX |
| 10 | RX2 | 16 | UART2 RX |
| 11 | D4 | 4 | PWM, TOUCH |
| 12 | D2 | 2 | LED on-board / strapping |
| 13 | D15 | 15 | PWM, strapping |
| 14 | GND | – | Terra |
| 15 | 3V3 | – | Saída 3,3 V |

## 2. Pinos que você deve evitar

| Pino | Motivo |
|---|---|
| GPIO34, 35, 36, 39 | **Só entrada.** Sem saída e sem pull-up/pull-down interno |
| GPIO1, 3 | UART0. Ocupados pelo monitor serial ao conectar via USB |
| GPIO0, 2, 5, 12, 15 | *Strapping*: definem o modo de boot. Deixe soltos ou no nível correto ao ligar |
| GPIO6–11 | Não existem neste módulo (ligados ao flash) |
| GPIO12 | Tem pull-down interno: segure em LOW ao boot, senão o chip não sobe |

## 3. Regra de ouro dos jumpers

1. **Alimente a protoboard pelo ESP32**: jumper `3V3` → trilho vermelho (+), jumper `GND` → trilho azul (−).
2. **Nunca alimente a protoboard por VIN e 3V3 ao mesmo tempo** — os caminhos se encontram dentro da placa e pode queimar.
3. **Distribua os fios nas extremidades**: o + no canto esquerdo superior, o − no canto direito inferior (ou vice-versa), para os fios não ficarem na frente dos componentes.
4. **Centralize os componentes sobre o canal** (o meio em "T") da protoboard: cada pé fica num trilho diferente e os dois lados se comunicam pela linha de terra.
5. **Linhas de energia são as mais longas** da protoboard —留给 o meio para os sensores.

## 4. Jumpers por tipo de função

### 4.1 Pinos livres para uso geral (os mais seguros)

`GPIO4, 13, 14, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33`

Comece sempre por aqui. Saem Output, Input, PWM e grande parte suporta I2C/SPI.

### 4.2 Sensores e módulos comuns

| Módulo | VCC | GND | Sinal |
|---|---|---|---|
| DHT11 / DHT22 | 3V3 | GND | GPIO4 |
| HC-SR04 (ultrassom) | 5 V (VIN) | GND | Trig → GPIO5 · Echo → GPIO18 (via divisor 1k2/2k2) |
| LDR / fotoresistor | 3V3 | GND | Meio do divisor (1 kΩ ↔ LDR) → GPIO34 |
| PIR (HC-SR501) | 5 V (VIN) | GND | GPIO13 |
| Botão | 3V3 | GND | GPIO14 + resistor 10 kΩ |
| Módulo relé | 5 V (VIN) | GND | GPIO27 |
| Módulo LED | 3V3 ou 5 V | GND | GPIO26 + resistor 220–330 Ω |

> **Atenção ao HC-SR04:** ele trabalha em 5 V e o `Echo` devolve 5 V, que **não é tolerante** ao ESP32. Use divisor de tensão: `Echo → 1 kΩ → GPIO18 → 2 kΩ → GND`.

### 4.3 I2C

| Dispositivo | SDA | SCL |
|---|---|---|
| LCD 16x2 (PCF8574) | GPIO21 | GPIO22 |
| BME280 / BME680 | GPIO21 | GPIO22 |
| MPU6050 / MPU9250 | GPIO21 | GPIO22 |
| RTC DS3231 | GPIO21 | GPIO22 |

Padrão de biblioteca Arduino: `Wire.begin(21, 22)`.

Muitos módulos já trazem pull-ups de 4,7 kΩ. **Não duplique** — dois pull-ups em paralelo dão ~2,3 kΩ, ainda ok, mas com 3 ou mais fica forte demais.

### 4.4 SPI (cartão SD, TFT, displays)

| Sinal | GPIO |
|---|---|
| SCK (CLK) | GPIO18 |
| MOSI | GPIO23 |
| MISO | GPIO19 |
| CS (SS) | GPIO5 |

Para SD Card com `SD.h`: `SD.begin(5, 18, 19, 23)`.

### 4.5 UART (outros ESP / conversores USB-TTL)

| Função | GPIO | Nota |
|---|---|---|
| UART0 TX / RX | GPIO1 / GPIO3 | Já usado pelo USB da placa — use pinos livres |
| UART2 TX / RX | GPIO17 / GPIO16 | Alternativa livre e segura |
| UART1 TX / RX | GPIO9 / GPIO10 | Também seguros (GPIO9 = boot log) |

Padrão de biblioteca: `Serial2.begin(115200, SERIAL_8N1, 16, 17)`.

## 5. Analogias

| ADC1 (com WiFi) | ADC2 (quebra com WiFi) |
|---|---|
| GPIO32, 33, 34, 35, 36, 39 | GPIO0, 2, 4, 12, 13, 14, 15, 25, 26, 27 |

- **ADC1** funciona normalmente com WiFi ligado.
- **ADC2** só funciona com o WiFi **desligado**. Se estiver lendo sensor analógico, não ative WiFi — ou mova o sensor para um ADC1.

## 6. Cores de jumper recomendadas

| Cor | Destino |
|---|---|
| Vermelho | Alimentação + (3V3 / 5 V) |
| Preto | GND |
| Amarelo | Sinal de dados (I2C, SPI, UART) |
| Verde | Sinal de controle (trigger, enable) |
| Azul | Entrada de sensor / botão |
| Branco | Sinal auxiliar |

Se não tiver cores, **regra prática**: dois vermelhos e dois pretos vão para a protoboard; o resto é sinal.

## 7. Checklist antes de ligar

- [ ] Nenhum jumper em GPIO34/35/36/39 esperando saída
- [ ] GPIO12 não está puxado para HIGH
- [ ] Nenhum fio em TX0/RX0 se você quer o monitor serial
- [ ] Protoboard alimentada por **uma** fonte só (3V3 ou VIN, nunca as duas)
- [ ] Nenhum motor, servo ou relé powered direto pelo 3V3 do ESP32 (o regulador não aguenta)
- [ ] Fios de sinal das duas pontas realmente em linhas diferentes (e não na mesma linha, emendados)
