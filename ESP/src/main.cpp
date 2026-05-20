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
//
// WebSocket (port 81): every byte seen on the CSAFE line, streamed as
//   {"dir":"tx"|"rx","hex":"..."} for live signal analysis.

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include <WebServer.h>
#include <WebSocketsServer.h>
#include <ArduinoJson.h>

#include "config.h"
#include "csafe.h"

static HardwareSerial CSAFE(2);
static WebServer server(HTTP_PORT);
static WebSocketsServer wsSniff(WS_PORT);

static uint32_t g_baud = CSAFE_BAUD;

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
  doc["csafe"]["baud"] = g_baud;
  doc["csafe"]["rx_pin"] = CSAFE_RX_PIN;
  doc["csafe"]["tx_pin"] = CSAFE_TX_PIN;
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

static void decodeTelemetry(const std::vector<uint8_t>& payload,
                            JsonDocument& doc) {
  if (payload.empty()) return;
  doc["status"] = payload[0] & 0x0F;
  JsonObject fields = doc["fields"].to<JsonObject>();

  size_t i = 1, n = payload.size();
  while (i < n) {
    uint8_t op = payload[i++];
    if (i >= n) break;
    uint8_t len = payload[i++];
    if (i + len > n) break;
    const uint8_t* d = &payload[i];
    auto u16 = [&]() -> uint16_t { return d[0] | (d[1] << 8); };
    switch (op) {
      case csafe::GETTWORK:
        if (len >= 3) fields["elapsed_sec"] = d[0] * 3600 + d[1] * 60 + d[2];
        break;
      case csafe::GETHORIZONTAL:
        if (len >= 2) fields["distance_m"] = u16();
        break;
      case csafe::GETCALORIES:
        if (len >= 2) fields["calories"] = u16();
        break;
      case csafe::GETSPEED:
        if (len >= 2) fields["speed_kmh"] = u16() / 10.0;
        break;
      case csafe::GETCADENCE:
        if (len >= 2) fields["cadence_rpm"] = u16();
        break;
      case csafe::GETHRCUR:
        if (len >= 1) fields["heart_rate_bpm"] = d[0];
        break;
      case csafe::GETPOWER:
        if (len >= 2) fields["power_watts"] = u16();
        break;
      default:
        break;
    }
    i += len;
  }
}

static void handleTelemetry() {
  std::vector<uint8_t> frame = csafe::buildFrame(csafe::buildTelemetryPayload());
  std::vector<uint8_t> rx = txrx(frame, 500);

  JsonDocument res;
  res["rx_frame"] = bytesToHex(rx);

  csafe::FrameReader fr;
  std::vector<std::vector<uint8_t>> frames;
  for (uint8_t b : rx) fr.feed(b, frames);
  if (!frames.empty()) {
    res["ok"] = true;
    decodeTelemetry(frames[0], res);
  } else {
    res["ok"] = false;
  }

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

  server.on("/", HTTP_GET, handleStatus);
  server.on("/health", HTTP_GET, handleHealth);
  server.on("/csafe/telemetry", HTTP_GET, handleTelemetry);
  server.on("/csafe/raw", HTTP_POST, handleRaw);
  server.on("/csafe/frame", HTTP_POST, handleFrame);
  server.on("/serial/config", HTTP_POST, handleSerialConfig);
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
