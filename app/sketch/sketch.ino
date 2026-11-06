// AquaSense - STM32U585 side of the Arduino UNO Q
//
// Linux (python/main.py) decides when the water should be measured. This sketch
// does the measuring: it powers one probe at a time (pH, DO and EC boards
// interfere with each other when they share the same water), waits for the
// probe to settle, averages 64 ADC samples and switches the probe off again.
// Only raw millivolts go back to Linux, calibration is done in Python.
//
// Functions called from Python through the Bridge (all return immediately,
// the measurement itself runs in loop()):
//   aq_ping, aq_start(mask), aq_status, aq_result, aq_abort,
//   aq_indicator(level), aq_buzzer(on), aq_aerator(on), aq_set_warmup(ch, ms)

#include <Arduino_RouterBridge.h>
#include <Wire.h>
#include <math.h>

#include "config.h"
#include "ds2484.h"

enum SensorBit : uint8_t { S_TEMP = 1, S_PH = 2, S_DO = 4, S_EC = 8, S_TURB = 16 };

struct Channel {
  uint8_t bit;
  uint8_t pinEnable;
  uint8_t pinAdc;
  uint32_t warmupMs;
  float mv;  // last result, NAN if not measured
};

static Channel channels[] = {
    {S_PH, PIN_EN_PH, PIN_ADC_PH, WARMUP_PH_MS, NAN},
    {S_DO, PIN_EN_DO, PIN_ADC_DO, WARMUP_DO_MS, NAN},
    {S_EC, PIN_EN_EC, PIN_ADC_EC, WARMUP_EC_MS, NAN},
    {S_TURB, PIN_EN_TURB, PIN_ADC_TURB, WARMUP_TURB_MS, NAN},
};
static const uint8_t N_CH = sizeof(channels) / sizeof(channels[0]);

#if TEMP_SENSOR == TEMP_SENSOR_DS2484
static DS2484 owBridge(TEMP_I2C_BUS, DS2484_ADDR);
static DS18B20 thermo(owBridge);
static bool owReady = false;
#endif

enum Phase : uint8_t { PH_IDLE, PH_TEMP_WAIT, PH_NEXT, PH_WARMUP, PH_DONE };
static const char *const STATE_NAMES[] = {"IDLE", "BUSY", "BUSY", "BUSY", "DONE"};
enum Flags : uint8_t { F_TEMP_FAIL = 0x01, F_ADC_SAT = 0x02, F_TIMEOUT = 0x08 };

static Phase phase = PH_IDLE;
static uint8_t reqMask = 0;
static uint8_t flags = 0;
static int8_t chIdx = -1;
static uint8_t stepNo = 0, stepTotal = 0;
static uint32_t seq = 0;
static uint32_t phaseStart = 0;
static float tempC = NAN;

static uint8_t indicatorLevel = 255;  // 255 = no status from Linux yet, LED off
static bool buzzerOn = false;
static uint32_t lastRpcMs = 0;
static bool rpcSeen = false;           // Linux has called us at least once

// ---------------------------------------------------------------- helpers

static void allProbesOff() {
  for (uint8_t i = 0; i < N_CH; i++) digitalWrite(channels[i].pinEnable, LOW);
}

// String(float) is not reliable on every core, so format by hand
static void appendFixed(String &s, float v, uint8_t decimals) {
  if (isnan(v)) {
    s += "nan";
    return;
  }
  long scale = 1;
  for (uint8_t i = 0; i < decimals; i++) scale *= 10;
  long q = lroundf(v * scale);
  if (q < 0) {
    s += '-';
    q = -q;
  }
  s += String(q / scale);
  if (decimals) {
    s += '.';
    String frac = String(q % scale);
    while (frac.length() < decimals) frac = "0" + frac;
    s += frac;
  }
}

static int cmpU16(const void *a, const void *b) {
  return (int)*(const uint16_t *)a - (int)*(const uint16_t *)b;
}

// 64 samples, drop the highest and lowest 8, average the rest
static float readMillivolts(uint8_t pin, bool &saturated) {
  static uint16_t buf[ADC_SAMPLES];
  const uint16_t maxCount = (1u << ADC_BITS) - 1;
  for (uint16_t i = 0; i < ADC_SAMPLES; i++) {
    buf[i] = (uint16_t)analogRead(pin);
    delay(ADC_SAMPLE_GAP_MS);
  }
  qsort(buf, ADC_SAMPLES, sizeof(uint16_t), cmpU16);
  const uint16_t cut = ADC_SAMPLES / 8;
  uint32_t sum = 0;
  for (uint16_t i = cut; i < ADC_SAMPLES - cut; i++) sum += buf[i];
  saturated = buf[ADC_SAMPLES - cut - 1] >= maxCount - 2;
  return (float)sum / (ADC_SAMPLES - 2 * cut) * ADC_VREF_MV / maxCount;
}

#if TEMP_SENSOR == TEMP_SENSOR_NTC
static float readNtcCelsius() {
  bool sat = false;
  const float mv = readMillivolts(PIN_ADC_NTC, sat);
  if (mv <= 1.0f || mv >= ADC_VREF_MV - 1.0f) return NAN;
  const float r = NTC_R_FIXED * mv / (ADC_VREF_MV - mv);
  return 1.0f / (1.0f / 298.15f + logf(r / NTC_R25) / NTC_BETA) - 273.15f;
}
#endif

// on-board RGB LEDs are active low
static void setLed3(bool r, bool g, bool b) {
  digitalWrite(LED3_R, r ? LOW : HIGH);
  digitalWrite(LED3_G, g ? LOW : HIGH);
  digitalWrite(LED3_B, b ? LOW : HIGH);
}

static void showLevel() {
  switch (indicatorLevel) {
    case 255: setLed3(false, false, false); break; // off    - no status yet
    case 0: setLed3(false, true, false); break;   // green  - water ok
    case 1: setLed3(false, false, true); break;   // blue   - measuring
    case 2: setLed3(true, true, false); break;    // yellow - warning
    default: setLed3(true, false, false); break;  // red    - critical
  }
}

// ------------------------------------------------------------ measuring

static void nextChannel() {
  for (int8_t i = chIdx + 1; i < (int8_t)N_CH; i++) {
    if (reqMask & channels[i].bit) {
      chIdx = i;
      stepNo++;
      digitalWrite(channels[i].pinEnable, HIGH);
      phaseStart = millis();
      phase = PH_WARMUP;
      return;
    }
  }
  allProbesOff();
  phase = PH_DONE;
}

static void runMeasurement() {
  const uint32_t now = millis();
  switch (phase) {
    case PH_TEMP_WAIT:
#if TEMP_SENSOR == TEMP_SENSOR_DS2484
      if (now - phaseStart < DS18B20_CONVERT_MS) return;
      if (!thermo.readCelsius(tempC)) {
        tempC = NAN;
        flags |= F_TEMP_FAIL;
      }
#endif
      phase = PH_NEXT;
      return;

    case PH_NEXT:
      nextChannel();
      return;

    case PH_WARMUP: {
      Channel &ch = channels[chIdx];
      if (now - phaseStart > MAX_RAIL_ON_MS) {  // should not happen, but never leave a probe on
        flags |= F_TIMEOUT;
        digitalWrite(ch.pinEnable, LOW);
        phase = PH_NEXT;
        return;
      }
      if (now - phaseStart < ch.warmupMs) return;
      bool sat = false;
      ch.mv = readMillivolts(ch.pinAdc, sat);
      if (sat) flags |= F_ADC_SAT;
      digitalWrite(ch.pinEnable, LOW);
      phase = PH_NEXT;
      return;
    }
    default:
      return;
  }
}

static bool startMeasurement(uint8_t mask) {
  if (phase != PH_IDLE && phase != PH_DONE) return false;
  if ((mask & 0x1F) == 0) return false;
  reqMask = mask;
  flags = 0;
  chIdx = -1;
  stepNo = 0;
  stepTotal = 0;
  tempC = NAN;
  for (uint8_t i = 0; i < N_CH; i++) {
    channels[i].mv = NAN;
    if (mask & channels[i].bit) stepTotal++;
  }
  seq++;
  phase = PH_NEXT;
  if (mask & S_TEMP) {
    stepTotal++;
    stepNo = 1;
#if TEMP_SENSOR == TEMP_SENSOR_DS2484
    if (!owReady) owReady = owBridge.begin();
    if (owReady && thermo.startConversion()) {
      phaseStart = millis();
      phase = PH_TEMP_WAIT;
    } else {
      flags |= F_TEMP_FAIL;
    }
#else
    tempC = readNtcCelsius();
    if (isnan(tempC)) flags |= F_TEMP_FAIL;
#endif
  }
  return true;
}

// ------------------------------------------------------- Bridge functions

String aq_ping() {
  lastRpcMs = millis();
  rpcSeen = true;
  return String("AquaSense MCU " FW_VERSION);
}

int aq_start(int mask) {
  lastRpcMs = millis();
  rpcSeen = true;
  return startMeasurement((uint8_t)mask) ? 1 : 0;
}

String aq_status() {
  lastRpcMs = millis();
  rpcSeen = true;
  String s = STATE_NAMES[phase];
  s += ',';
  s += String(stepNo);
  s += ',';
  s += String(stepTotal);
  s += ',';
  s += String(seq);
  return s;
}

// e.g. "R1;seq=12;t=27.94;ph=1561.2;do=702.4;ec=74.9;tu=2790.3;f=0"
// (Bridge messages are limited to 256 bytes, this is < 100)
String aq_result() {
  lastRpcMs = millis();
  rpcSeen = true;
  if (phase != PH_DONE) return String("");
  String s = "R1;seq=";
  s += String(seq);
  s += ";t=";
  appendFixed(s, tempC, 2);
  const char *keys[] = {";ph=", ";do=", ";ec=", ";tu="};
  for (uint8_t i = 0; i < N_CH; i++) {
    s += keys[i];
    appendFixed(s, channels[i].mv, 1);
  }
  s += ";f=";
  s += String(flags);
  return s;
}

int aq_abort() {
  lastRpcMs = millis();
  rpcSeen = true;
  allProbesOff();
  phase = PH_IDLE;
  return 1;
}

int aq_indicator(int level) {
  lastRpcMs = millis();
  rpcSeen = true;
  indicatorLevel = (uint8_t)constrain(level, 0, 3);
  showLevel();
  return 1;
}

int aq_buzzer(int on) {
  lastRpcMs = millis();
  rpcSeen = true;
  buzzerOn = on != 0;
  if (!buzzerOn) digitalWrite(PIN_BUZZER, LOW);
  return buzzerOn;
}

int aq_aerator(int on) {
  lastRpcMs = millis();
  rpcSeen = true;
  digitalWrite(PIN_AERATOR, on ? HIGH : LOW);
  return on != 0;
}

int aq_set_warmup(int channel, int ms) {
  lastRpcMs = millis();
  rpcSeen = true;
  if (channel < 1 || channel > (int)N_CH) return 0;
  channels[channel - 1].warmupMs = (uint32_t)constrain(ms, 0, (long)MAX_RAIL_ON_MS - 5000L);
  return 1;
}

// ------------------------------------------------------------ setup/loop

void setup() {
  // probes and outputs off before anything else
  for (uint8_t i = 0; i < N_CH; i++) {
    pinMode(channels[i].pinEnable, OUTPUT);
    digitalWrite(channels[i].pinEnable, LOW);
  }
  pinMode(PIN_AERATOR, OUTPUT);
  digitalWrite(PIN_AERATOR, LOW);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
  pinMode(LED3_R, OUTPUT);
  pinMode(LED3_G, OUTPUT);
  pinMode(LED3_B, OUTPUT);
  pinMode(LED4_R, OUTPUT);
  pinMode(LED4_G, OUTPUT);
  pinMode(LED4_B, OUTPUT);
  digitalWrite(LED4_R, HIGH);
  digitalWrite(LED4_G, HIGH);
  digitalWrite(LED4_B, HIGH);
  showLevel();

  // no pinMode() on the analog inputs: on the UNO Q core it stops analogRead() working
  analogReadResolution(ADC_BITS);

#if TEMP_SENSOR == TEMP_SENSOR_DS2484
  owReady = owBridge.begin();
#endif

  Bridge.begin();
  // provide_safe: the function runs between two loop() passes, so it can use digitalWrite etc.
  Bridge.provide_safe("aq_ping", aq_ping);
  Bridge.provide_safe("aq_start", aq_start);
  Bridge.provide_safe("aq_status", aq_status);
  Bridge.provide_safe("aq_result", aq_result);
  Bridge.provide_safe("aq_abort", aq_abort);
  Bridge.provide_safe("aq_indicator", aq_indicator);
  Bridge.provide_safe("aq_buzzer", aq_buzzer);
  Bridge.provide_safe("aq_aerator", aq_aerator);
  Bridge.provide_safe("aq_set_warmup", aq_set_warmup);
}

void loop() {
  runMeasurement();
  const uint32_t now = millis();

  if (buzzerOn) digitalWrite(PIN_BUZZER, (now % 1000) < 200 ? HIGH : LOW);

  // LED4: blue blink until Linux first calls us, then a green blink every 3 s
  // while it keeps talking (main.py pings every minute), red if it went quiet
  const bool linkLost = rpcSeen && now - lastRpcMs > LINK_TIMEOUT_MS;
  const bool blink = (now % 3000) < 80;
  digitalWrite(LED4_B, (blink && !rpcSeen) ? LOW : HIGH);
  digitalWrite(LED4_G, (blink && rpcSeen && !linkLost) ? LOW : HIGH);
  digitalWrite(LED4_R, (blink && linkLost) ? LOW : HIGH);

  delay(5);
}
