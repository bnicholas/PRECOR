// ESP-NOW telemetry receiver / USB-serial bridge.
//
// Pair with the CSAFE probe (../../src/main.cpp). When the probe has ESP-NOW
// enabled it broadcasts a TelemetryPacket; this receiver decodes each one and
// prints a JSON line over USB serial so a host program can consume it.
//
// IMPORTANT: ESP-NOW only hears peers on the same Wi-Fi channel. The probe,
// while connected as STA, uses its AP's channel. Set RX_CHANNEL to match
// (the probe reports it at `GET /` -> wifi.channel) and re-flash.

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "telemetry_packet.h"

#ifndef RX_CHANNEL
#define RX_CHANNEL 1
#endif

// The ESP-NOW receive-callback signature changed in arduino-esp32 3.x
// (IDF 5): older cores pass the source MAC, newer cores pass an info struct.
#if ESP_ARDUINO_VERSION_MAJOR >= 3
static void onRecv(const esp_now_recv_info_t* info, const uint8_t* data,
                   int len) {
  const uint8_t* m = info->src_addr;
#else
static void onRecv(const uint8_t* m, const uint8_t* data, int len) {
#endif
  if (len != (int)sizeof(TelemetryPacket)) return;
  TelemetryPacket p;
  memcpy(&p, data, sizeof(p));
  if (p.magic != TELEM_PACKET_MAGIC || p.version != TELEM_PACKET_VERSION) return;

  Serial.printf(
      "{\"src\":\"%02X:%02X:%02X:%02X:%02X:%02X\",\"seq\":%u,\"status\":%u,"
      "\"heart_rate_bpm\":%u,\"cadence_rpm\":%u,\"power_watts\":%u,"
      "\"speed_kmh\":%.1f,\"calories\":%u,\"distance_m\":%u,"
      "\"elapsed_sec\":%u}\n",
      m[0], m[1], m[2], m[3], m[4], m[5], (unsigned)p.seq, p.status,
      p.heart_rate, p.cadence, p.power, p.speed_dkmh / 10.0, p.calories,
      (unsigned)p.distance_m, (unsigned)p.elapsed_sec);
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(RX_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    return;
  }
  esp_now_register_recv_cb(onRecv);
  Serial.printf("ESP-NOW receiver up on channel %d. MAC %s\n", RX_CHANNEL,
                WiFi.macAddress().c_str());
}

void loop() { delay(1000); }
