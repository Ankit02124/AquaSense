// Minimal driver for the DS2484 / DS2482-100 I2C to 1-Wire bridge and one DS18B20.
// Uses only the Wire API, so it works on the Zephyr based UNO Q core.
#pragma once
#include <Arduino.h>
#include <Wire.h>

class DS2484 {
 public:
  explicit DS2484(TwoWire &wire, uint8_t addr = 0x18) : _w(wire), _addr(addr) {}

  // Reset the bridge and enable the active pull-up (APU).
  bool begin() {
    _w.begin();
    if (!command(0xF0)) return false;           // Device Reset
    uint8_t st = 0;
    if (!readByteRaw(st) || !(st & ST_RST)) return false;
    const uint8_t cfg = 0x01;                   // APU = 1
    if (!command(0xD2, (uint8_t)(cfg | ((~cfg & 0x0F) << 4)))) return false;
    uint8_t rb = 0;
    return readByteRaw(rb) && (rb & 0x0F) == cfg;
  }

  // 1-Wire reset; returns true when a presence pulse was detected.
  bool reset() {
    uint8_t st;
    if (!command(0xB4) || !waitIdle(st)) return false;
    return (st & ST_PPD) && !(st & ST_SD);
  }

  bool write(uint8_t b) {
    uint8_t st;
    return command(0xA5, b) && waitIdle(st);
  }

  bool read(uint8_t &b) {
    uint8_t st;
    if (!command(0x96) || !waitIdle(st)) return false;
    if (!command(0xE1, 0xE1)) return false;     // Set Read Pointer -> read-data register
    return readByteRaw(b);
  }

 private:
  static constexpr uint8_t ST_1WB = 0x01, ST_PPD = 0x02, ST_SD = 0x04, ST_RST = 0x10;
  TwoWire &_w;
  uint8_t _addr;

  bool command(uint8_t cmd) {
    _w.beginTransmission(_addr);
    _w.write(cmd);
    return _w.endTransmission() == 0;
  }
  bool command(uint8_t cmd, uint8_t arg) {
    _w.beginTransmission(_addr);
    _w.write(cmd);
    _w.write(arg);
    return _w.endTransmission() == 0;
  }
  bool readByteRaw(uint8_t &out) {
    if (_w.requestFrom((int)_addr, 1) != 1) return false;
    out = (uint8_t)_w.read();
    return true;
  }
  bool waitIdle(uint8_t &st, uint32_t timeout_ms = 20) {
    const uint32_t t0 = millis();
    do {
      if (!readByteRaw(st)) return false;
      if (!(st & ST_1WB)) return true;
    } while (millis() - t0 < timeout_ms);
    return false;
  }
};

// Single DS18B20 on the bus (Skip ROM), externally powered (VDD = 3.3 V).
class DS18B20 {
 public:
  explicit DS18B20(DS2484 &bus) : _bus(bus) {}

  bool startConversion() {
    return _bus.reset() && _bus.write(0xCC) && _bus.write(0x44);
  }

  bool readCelsius(float &out) {
    uint8_t sp[9];
    if (!_bus.reset() || !_bus.write(0xCC) || !_bus.write(0xBE)) return false;
    for (uint8_t i = 0; i < 9; i++) {
      if (!_bus.read(sp[i])) return false;
    }
    if (crc8(sp, 8) != sp[8]) return false;
    const int16_t raw = (int16_t)((sp[1] << 8) | sp[0]);
    out = raw / 16.0f;
    return out > -55.0f && out < 125.0f && !(raw == 0x0550);  // 85.0 C = power-on value
  }

 private:
  DS2484 &_bus;
  static uint8_t crc8(const uint8_t *d, uint8_t n) {
    uint8_t crc = 0;
    while (n--) {
      uint8_t in = *d++;
      for (uint8_t i = 0; i < 8; i++) {
        const uint8_t mix = (crc ^ in) & 0x01;
        crc >>= 1;
        if (mix) crc ^= 0x8C;
        in >>= 1;
      }
    }
    return crc;
  }
};
