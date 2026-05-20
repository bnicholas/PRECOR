#pragma once

// Central configuration for the CSAFE ESP32 probe.
//
// Secrets (Wi-Fi, OTA password) belong in secrets.h, which is gitignored.
// Copy secrets.example.h -> secrets.h and fill it in, or override any of these
// via PlatformIO build_flags (e.g. -DWIFI_SSID='"net"').

#if __has_include("secrets.h")
#include "secrets.h"
#endif

#define FIRMWARE_VERSION "0.1.0"

// --- Wi-Fi ------------------------------------------------------------------
#ifndef WIFI_SSID
#define WIFI_SSID "your-ssid"
#endif
#ifndef WIFI_PASS
#define WIFI_PASS "your-pass"
#endif

// --- OTA (lets Claude Code / you push firmware over the air) ----------------
#ifndef OTA_HOSTNAME
#define OTA_HOSTNAME "precor-csafe-esp"
#endif
#ifndef OTA_PASSWORD
#define OTA_PASSWORD "precor-ota"
#endif

// --- HTTP / WebSocket ports -------------------------------------------------
#ifndef HTTP_PORT
#define HTTP_PORT 80
#endif
#ifndef WS_PORT
#define WS_PORT 81
#endif

// --- CSAFE serial link ------------------------------------------------------
// ESP32 UART2. These are 3.3 V TTL pins: they MUST pass through a MAX3232 (or
// equivalent) RS-232 level shifter before reaching the CSAFE RJ45. See
// docs/wiring.md.
//
// SAFETY: CSAFE RJ45 pin 3 carries 4.75-10 V from the machine. NEVER connect
// it to the ESP32 or the level shifter's signal pins.
#ifndef CSAFE_RX_PIN
#define CSAFE_RX_PIN 16  // ESP32 RX2  <- MAX3232 TTL out (machine TXD)
#endif
#ifndef CSAFE_TX_PIN
#define CSAFE_TX_PIN 17  // ESP32 TX2  -> MAX3232 TTL in  (machine RXD)
#endif
#ifndef CSAFE_BAUD
#define CSAFE_BAUD 9600  // CSAFE physical layer is 9600 8N1
#endif
