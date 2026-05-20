#pragma once

// Wire format for telemetry broadcast over ESP-NOW.
//
// Shared, single source of truth for both the probe firmware (sender) and the
// examples/espnow_receiver project (receiver). Packed for a stable byte layout
// across builds; 24 bytes, well under the 250-byte ESP-NOW payload limit.
//
// Absent/unknown values are sent as 0 (and status as 0xFF). A receiver that
// needs to distinguish "0" from "unknown" should track field freshness itself.

#include <stdint.h>

#define TELEM_PACKET_MAGIC 0xC5  // 'CSAFE'
#define TELEM_PACKET_VERSION 1

typedef struct __attribute__((packed)) {
  uint8_t magic;        // TELEM_PACKET_MAGIC
  uint8_t version;      // TELEM_PACKET_VERSION
  uint8_t status;       // CSAFE state nibble, 0xFF if unknown
  uint8_t heart_rate;   // bpm
  uint16_t cadence;     // rpm / spm
  uint16_t power;       // watts
  uint16_t speed_dkmh;  // 0.1 km/h
  uint16_t calories;    // kcal
  uint32_t distance_m;  // meters
  uint32_t elapsed_sec; // seconds
  uint32_t seq;         // monotonic sequence counter from the probe
} TelemetryPacket;
