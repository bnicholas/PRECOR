// Precor CSAFE ESP32 probe.
//
// A Wi-Fi "Swiss Army knife" that sits on a machine's CSAFE port and exposes
// an HTTP + WebSocket API so we can poke at the protocol and make sense of the
// signals while building the gaming prototype. Firmware is OTA-updatable.
//
// HTTP (port 80, JSON, CORS-open):
//   GET  /                    device + link status
//   GET  /health              liveness
//   GET  /csafe/telemetry     run the standard poll, return decoded fields
//   POST /csafe/raw           {hex, timeout_ms?}        send raw bytes, get raw back
//   POST /csafe/frame         {payload, extended?, timeout_ms?}  auto-frame a payload
//   POST /serial/config       {baud}                    re-tune the UART on the fly
//   POST /espnow              {enabled?, interval_ms?}  ESP-NOW telemetry broadcast
//
// WebSocket (port 81): every byte seen on the CSAFE line, streamed as
//   {"dir":"tx"|"rx","hex":"..."} for live signal analysis.
//
// ESP-NOW: when enabled, the probe polls telemetry and broadcasts a compact
// binary TelemetryPacket (see include/telemetry_packet.h) for a low-latency
// game host to consume. See examples/espnow_receiver.

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include <WebServer.h>
#include <WebSocketsServer.h>
#include <ArduinoJson.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "config.h"
#include "csafe.h"
#include "telemetry_packet.h"

static HardwareSerial CSAFE(2);
static WebServer server(HTTP_PORT);
static WebSocketsServer wsSniff(WS_PORT);

static uint32_t g_baud = CSAFE_BAUD;

// ESP-NOW broadcast state.
static const uint8_t BROADCAST_ADDR[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static bool g_espnowReady = false;
static bool g_espnowEnabled = ESPNOW_ENABLED;
static uint32_t g_espnowIntervalMs = ESPNOW_INTERVAL_MS;
static uint32_t g_espnowSeq = 0;

// ---------------------------------------------------------------------------
// hex helpers
// ---------------------------------------------------------------------------

static String bytesToHex(const uint8_t* data, size_t len) {
  static const char* H = "0123456789ABCDEF";
  String s;
  s.reserve(len * 2);
  for (size_t i = 0; i < len; ++i) {
    s += H[data[i] >> 4];
    s += H[data[i] & 0x0F];
  }
  return s;
}

static String bytesToHex(const std::vector<uint8_t>& v) {
  return bytesToHex(v.data(), v.size());
}

// broadcastTXT(String&) wants a non-const lvalue; route temporaries through
// the const char* overload instead.
static void wsBroadcast(const String& s) { wsSniff.broadcastTXT(s.c_str()); }

static bool hexToBytes(const String& hex, std::vector<uint8_t>& out) {
  auto nib = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  };
  int hi = -1;
  for (size_t i = 0; i < hex.length(); ++i) {
    char c = hex[i];
    if (c == ' ' || c == ':' || c == ',' || c == '\n' || c == '\r' ||
        c == '\t') {
      continue;  // tolerate separators
    }
    int v = nib(c);
    if (v < 0) return false;
    if (hi < 0) {
      hi = v;
    } else {
      out.push_back((uint8_t)((hi << 4) | v));
      hi = -1;
    }
  }
  return hi < 0;  // false if a dangling nibble was left
}

// ---------------------------------------------------------------------------
// CSAFE serial transaction
// ---------------------------------------------------------------------------

// Write tx to the CSAFE line, then collect the reply. Returns after either
// `timeoutMs` total elapses or `idleMs` of silence following the first byte.
// Both directions are mirrored to WebSocket sniffers.
static std::vector<uint8_t> txrx(const std::vector<uint8_t>& tx,
                                 uint32_t timeoutMs, uint32_t idleMs = 60) {
  while (CSAFE.available()) CSAFE.read();  // drain stale input

  if (!tx.empty()) {
    CSAFE.write(tx.data(), tx.size());
    CSAFE.flush();
    wsBroadcast("{\"dir\":\"tx\",\"hex\":\"" + bytesToHex(tx) + "\"}");
  }

  std::vector<uint8_t> rx;
  uint32_t start = millis();
  uint32_t lastByte = start;
  while (millis() - start < timeoutMs) {
    if (CSAFE.available()) {
      rx.push_back((uint8_t)CSAFE.read());
      lastByte = millis();
    } else if (!rx.empty() && millis() - lastByte > idleMs) {
      break;
    } else {
      delay(1);
    }
  }

  if (!rx.empty()) {
    wsBroadcast("{\"dir\":\"rx\",\"hex\":\"" + bytesToHex(rx) + "\"}");
  }
  return rx;
}

// ---------------------------------------------------------------------------
// HTTP handlers
// ---------------------------------------------------------------------------

static void sendJson(int code, const String& body) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(code, "application/json", body);
}

static bool readJsonBody(JsonDocument& doc) {
  return !deserializeJson(doc, server.arg("plain"));
}

static void handleStatus() {
  JsonDocument doc;
  doc["firmware"] = FIRMWARE_VERSION;
  doc["device"] = OTA_HOSTNAME;
  doc["uptime_ms"] = millis();
  doc["free_heap"] = ESP.getFreeHeap();
  doc["wifi"]["ssid"] = WiFi.SSID();
  doc["wifi"]["ip"] = WiFi.localIP().toString();
  doc["wifi"]["rssi"] = WiFi.RSSI();
  doc["wifi"]["channel"] = WiFi.channel();
  doc["wifi"]["mac"] = WiFi.macAddress();
  doc["csafe"]["baud"] = g_baud;
  doc["csafe"]["rx_pin"] = CSAFE_RX_PIN;
  doc["csafe"]["tx_pin"] = CSAFE_TX_PIN;
  doc["espnow"]["enabled"] = g_espnowEnabled;
  doc["espnow"]["ready"] = g_espnowReady;
  doc["espnow"]["interval_ms"] = g_espnowIntervalMs;
  doc["espnow"]["seq"] = g_espnowSeq;
  String out;
  serializeJson(doc, out);
  sendJson(200, out);
}

static void handleHealth() { sendJson(200, "{\"ok\":true}"); }

static void handleRaw() {
  JsonDocument req;
  if (!readJsonBody(req)) {
    sendJson(400, "{\"error\":\"invalid json\"}");
    return;
  }
  std::vector<uint8_t> tx;
  if (!hexToBytes(req["hex"] | "", tx)) {
    sendJson(400, "{\"error\":\"invalid hex\"}");
    return;
  }
  uint32_t timeout = req["timeout_ms"] | 300;
  std::vector<uint8_t> rx = txrx(tx, timeout);

  JsonDocument res;
  res["tx"] = bytesToHex(tx);
  res["rx"] = bytesToHex(rx);
  res["rx_len"] = rx.size();
  String out;
  serializeJson(res, out);
  sendJson(200, out);
}

static void handleFrame() {
  JsonDocument req;
  if (!readJsonBody(req)) {
    sendJson(400, "{\"error\":\"invalid json\"}");
    return;
  }
  std::vector<uint8_t> payload;
  if (!hexToBytes(req["payload"] | "", payload)) {
    sendJson(400, "{\"error\":\"invalid payload hex\"}");
    return;
  }
  bool extended = req["extended"] | false;
  uint32_t timeout = req["timeout_ms"] | 300;

  std::vector<uint8_t> frame = csafe::buildFrame(payload, extended);
  std::vector<uint8_t> rx = txrx(frame, timeout);

  JsonDocument res;
  res["tx_payload"] = bytesToHex(payload);
  res["tx_frame"] = bytesToHex(frame);
  res["rx_frame"] = bytesToHex(rx);

  csafe::FrameReader fr;
  std::vector<std::vector<uint8_t>> frames;
  for (uint8_t b : rx) fr.feed(b, frames);
  if (!frames.empty()) {
    res["rx_ok"] = true;
    res["rx_payload"] = bytesToHex(frames[0]);
  } else {
    res["rx_ok"] = false;
  }

  String out;
  serializeJson(res, out);
  sendJson(200, out);
}

// Decoded telemetry. -1 marks an absent field (status -1 = no frame parsed).
struct Telemetry {
  int status = -1;
  long elapsed_sec = -1;
  long distance_m = -1;
  long calories = -1;
  int speed_dkmh = -1;  // 0.1 km/h
  int cadence_rpm = -1;
  int heart_rate_bpm = -1;
  int power_watts = -1;
  bool valid() const { return status >= 0; }
};

static Telemetry parseTelemetry(const std::vector<uint8_t>& payload) {
  Telemetry t;
  if (payload.empty()) return t;
  t.status = payload[0] & 0x0F;
  size_t i = 1, n = payload.size();
  while (i < n) {
    uint8_t op = payload[i++];
    if (i >= n) break;
    uint8_t len = payload[i++];
    if (i + len > n) break;
    const uint8_t* d = &payload[i];
    auto u16 = [&]() -> int { return d[0] | (d[1] << 8); };
    switch (op) {
      case csafe::GETTWORK:
        if (len >= 3) t.elapsed_sec = d[0] * 3600 + d[1] * 60 + d[2];
        break;
      case csafe::GETHORIZONTAL:
        if (len >= 2) t.distance_m = u16();
        break;
      case csafe::GETCALORIES:
        if (len >= 2) t.calories = u16();
        break;
      case csafe::GETSPEED:
        if (len >= 2) t.speed_dkmh = u16();
        break;
      case csafe::GETCADENCE:
        if (len >= 2) t.cadence_rpm = u16();
        break;
      case csafe::GETHRCUR:
        if (len >= 1) t.heart_rate_bpm = d[0];
        break;
      case csafe::GETPOWER:
        if (len >= 2) t.power_watts = u16();
        break;
      default:
        break;
    }
    i += len;
  }
  return t;
}

// Poll the standard telemetry frame; optionally return the raw rx bytes.
static Telemetry pollTelemetry(std::vector<uint8_t>* rawOut = nullptr) {
  std::vector<uint8_t> frame = csafe::buildFrame(csafe::buildTelemetryPayload());
  std::vector<uint8_t> rx = txrx(frame, 500);
  if (rawOut) *rawOut = rx;
  csafe::FrameReader fr;
  std::vector<std::vector<uint8_t>> frames;
  for (uint8_t b : rx) fr.feed(b, frames);
  if (frames.empty()) return Telemetry{};
  return parseTelemetry(frames[0]);
}

static void telemetryToJson(const Telemetry& t, JsonDocument& doc) {
  if (!t.valid()) return;
  doc["status"] = t.status;
  JsonObject f = doc["fields"].to<JsonObject>();
  if (t.elapsed_sec >= 0) f["elapsed_sec"] = t.elapsed_sec;
  if (t.distance_m >= 0) f["distance_m"] = t.distance_m;
  if (t.calories >= 0) f["calories"] = t.calories;
  if (t.speed_dkmh >= 0) f["speed_kmh"] = t.speed_dkmh / 10.0;
  if (t.cadence_rpm >= 0) f["cadence_rpm"] = t.cadence_rpm;
  if (t.heart_rate_bpm >= 0) f["heart_rate_bpm"] = t.heart_rate_bpm;
  if (t.power_watts >= 0) f["power_watts"] = t.power_watts;
}

static TelemetryPacket packTelemetry(const Telemetry& t, uint32_t seq) {
  TelemetryPacket p = {};
  p.magic = TELEM_PACKET_MAGIC;
  p.version = TELEM_PACKET_VERSION;
  p.status = (t.status >= 0) ? (uint8_t)t.status : 0xFF;
  p.heart_rate = (t.heart_rate_bpm >= 0) ? (uint8_t)t.heart_rate_bpm : 0;
  p.cadence = (t.cadence_rpm >= 0) ? (uint16_t)t.cadence_rpm : 0;
  p.power = (t.power_watts >= 0) ? (uint16_t)t.power_watts : 0;
  p.speed_dkmh = (t.speed_dkmh >= 0) ? (uint16_t)t.speed_dkmh : 0;
  p.calories = (t.calories >= 0) ? (uint16_t)t.calories : 0;
  p.distance_m = (t.distance_m >= 0) ? (uint32_t)t.distance_m : 0;
  p.elapsed_sec = (t.elapsed_sec >= 0) ? (uint32_t)t.elapsed_sec : 0;
  p.seq = seq;
  return p;
}

static void handleTelemetry() {
  std::vector<uint8_t> rx;
  Telemetry t = pollTelemetry(&rx);

  JsonDocument res;
  res["rx_frame"] = bytesToHex(rx);
  res["ok"] = t.valid();
  telemetryToJson(t, res);

  String out;
  serializeJson(res, out);
  sendJson(200, out);
}

static void handleSerialConfig() {
  JsonDocument req;
  if (!readJsonBody(req)) {
    sendJson(400, "{\"error\":\"invalid json\"}");
    return;
  }
  uint32_t baud = req["baud"] | 0;
  if (baud == 0) {
    sendJson(400, "{\"error\":\"baud required\"}");
    return;
  }
  g_baud = baud;
  CSAFE.updateBaudRate(baud);
  sendJson(200, String("{\"baud\":") + baud + "}");
}

static void onWsEvent(uint8_t, WStype_t, uint8_t*, size_t) {
  // Read-only sniff stream; inbound WS messages are ignored.
}

// ---------------------------------------------------------------------------
// ESP-NOW telemetry broadcast
// ---------------------------------------------------------------------------

static bool espnowInit() {
  if (esp_now_init() != ESP_OK) return false;

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST_ADDR, 6);
  peer.channel = 0;  // 0 = follow the current Wi-Fi (STA) channel
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;  // ESP-NOW broadcast cannot be encrypted
  if (esp_now_add_peer(&peer) != ESP_OK) return false;

  g_espnowReady = true;
  return true;
}

static void espnowBroadcast(const TelemetryPacket& p) {
  esp_now_send(BROADCAST_ADDR, (const uint8_t*)&p, sizeof(p));
}

static void handleEspnow() {
  JsonDocument req;
  if (!readJsonBody(req)) {
    sendJson(400, "{\"error\":\"invalid json\"}");
    return;
  }
  if (req["enabled"].is<bool>()) g_espnowEnabled = req["enabled"];
  if (!req["interval_ms"].isNull()) {
    uint32_t iv = req["interval_ms"] | g_espnowIntervalMs;
    if (iv >= 20) g_espnowIntervalMs = iv;
  }

  JsonDocument res;
  res["enabled"] = g_espnowEnabled;
  res["ready"] = g_espnowReady;
  res["interval_ms"] = g_espnowIntervalMs;
  res["channel"] = WiFi.channel();
  res["mac"] = WiFi.macAddress();
  res["payload_bytes"] = (int)sizeof(TelemetryPacket);
  String out;
  serializeJson(res, out);
  sendJson(200, out);
}

// ---------------------------------------------------------------------------
// setup / loop
// ---------------------------------------------------------------------------

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(OTA_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("Connecting to Wi-Fi \"%s\"", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("Wi-Fi up: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("Wi-Fi not connected; will keep retrying in loop().");
  }
}

void setup() {
  Serial.begin(115200);
  CSAFE.begin(g_baud, SERIAL_8N1, CSAFE_RX_PIN, CSAFE_TX_PIN);

  connectWifi();

  if (MDNS.begin(OTA_HOSTNAME)) {
    MDNS.addService("http", "tcp", HTTP_PORT);
  }

  ArduinoOTA.setHostname(OTA_HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.begin();

  if (espnowInit()) {
    Serial.println("ESP-NOW ready (broadcast peer registered).");
  } else {
    Serial.println("ESP-NOW init failed.");
  }

  server.on("/", HTTP_GET, handleStatus);
  server.on("/health", HTTP_GET, handleHealth);
  server.on("/csafe/telemetry", HTTP_GET, handleTelemetry);
  server.on("/csafe/raw", HTTP_POST, handleRaw);
  server.on("/csafe/frame", HTTP_POST, handleFrame);
  server.on("/serial/config", HTTP_POST, handleSerialConfig);
  server.on("/espnow", HTTP_POST, handleEspnow);
  server.onNotFound([]() {
    if (server.method() == HTTP_OPTIONS) {
      server.sendHeader("Access-Control-Allow-Origin", "*");
      server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
      server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
      server.send(204);
    } else {
      sendJson(404, "{\"error\":\"not found\"}");
    }
  });
  server.begin();

  wsSniff.begin();
  wsSniff.onEvent(onWsEvent);

  Serial.println("CSAFE ESP32 probe ready.");
}

void loop() {
  ArduinoOTA.handle();
  server.handleClient();
  wsSniff.loop();

  // Periodic ESP-NOW telemetry broadcast (when enabled).
  static uint32_t lastEspnow = 0;
  if (g_espnowEnabled && g_espnowReady &&
      millis() - lastEspnow >= g_espnowIntervalMs) {
    lastEspnow = millis();
    Telemetry t = pollTelemetry();
    TelemetryPacket p = packTelemetry(t, g_espnowSeq++);
    espnowBroadcast(p);
  }

  // Stream any unsolicited CSAFE traffic (e.g. when wired as a passive tap).
  if (CSAFE.available()) {
    std::vector<uint8_t> chunk;
    while (CSAFE.available() && chunk.size() < 256) {
      chunk.push_back((uint8_t)CSAFE.read());
    }
    wsBroadcast("{\"dir\":\"rx\",\"hex\":\"" + bytesToHex(chunk) + "\"}");
  }

  static uint32_t lastWifiCheck = 0;
  if (WiFi.status() != WL_CONNECTED && millis() - lastWifiCheck > 10000) {
    lastWifiCheck = millis();
    WiFi.reconnect();
  }
}
