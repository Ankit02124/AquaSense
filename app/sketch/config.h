// Pin and timing settings. Pin names follow the UNO Q silkscreen,
// see hardware/README.md for the wiring.
#pragma once

#define FW_VERSION "1.0"

// Analog inputs. A0-A5 take 0-3.3 V only, they are NOT 5 V tolerant in analog mode.
#define PIN_ADC_PH    A0   // pH board through the signal isolator
#define PIN_ADC_DO    A1   // dissolved oxygen board
#define PIN_ADC_EC    A2   // conductivity board through the signal isolator
#define PIN_ADC_TURB  A3   // turbidity sensor through a 10k/20k divider (4.5 V -> 3.0 V)
#define PIN_ADC_NTC   A4   // only used with TEMP_SENSOR_NTC

// Outputs (3.3 V logic)
#define PIN_EN_PH     D4   // probe power switches, HIGH = probe on
#define PIN_EN_DO     D5
#define PIN_EN_EC     D6
#define PIN_EN_TURB   D7
#define PIN_AERATOR   D8   // relay / SSR input
#define PIN_BUZZER    D9   // via BC547

// Water temperature. Default is a DS18B20 behind a DS2484 I2C-to-1-Wire bridge
// on the Qwiic port: bit-banged 1-Wire is not reliable on the Zephyr based core.
// A 10k NTC on A4 also works (-DTEMP_SENSOR=2).
#define TEMP_SENSOR_DS2484 1
#define TEMP_SENSOR_NTC    2
#ifndef TEMP_SENSOR
#define TEMP_SENSOR        TEMP_SENSOR_DS2484
#endif
#define TEMP_I2C_BUS       Wire1   // Wire1 = Qwiic connector, Wire = D20/D21
#define DS2484_ADDR        0x18
#define DS18B20_CONVERT_MS 800     // 12 bit conversion takes up to 750 ms

#define NTC_R_FIXED  10000.0f
#define NTC_R25      10000.0f
#define NTC_BETA     3950.0f

// ADC
#define ADC_BITS          12
#define ADC_VREF_MV       3300.0f  // measure your 3V3 pin and correct this for best accuracy
#define ADC_SAMPLES       64
#define ADC_SAMPLE_GAP_MS 2

// Probe warm-up times, Python overrides them from config.yaml at start-up
#define WARMUP_PH_MS     15000
#define WARMUP_DO_MS     10000
#define WARMUP_EC_MS     5000
#define WARMUP_TURB_MS   2000
#define MAX_RAIL_ON_MS   60000UL   // hard limit for any probe being powered
#define LINK_TIMEOUT_MS  900000UL  // LED4 turns red after 15 min without Bridge calls
