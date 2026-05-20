#pragma once

// CSAFE framing, byte-stuffing and checksum for the ESP32 probe.
//
// This is a direct port of the reference Python implementation in
// csafe_server/csafe/protocol.py + commands.py, so frames built here are
// wire-compatible with the Pi gateway.
//
// Standard frame on the wire:  F0 <stuffed payload+checksum> F2
//   * checksum  = XOR of every unstuffed payload byte
//   * stuffing  = reserved bytes F0..F3 become F3 (b - 0xF0)

#include <Arduino.h>
#include <vector>

namespace csafe {

constexpr uint8_t STD_START = 0xF0;
constexpr uint8_t EXT_START = 0xF1;
constexpr uint8_t END = 0xF2;
constexpr uint8_t ESCAPE = 0xF3;

// Opcode subset needed to drive the Precor P80 (AMT / RBK).
enum Cmd : uint8_t {
  // Short status / state transitions
  GETSTATUS = 0x80,
  RESET = 0x81,
  GOIDLE = 0x82,
  GOHAVEID = 0x83,
  GOINUSE = 0x85,
  GOFINISHED = 0x86,
  GOREADY = 0x87,
  // Short GETs
  GETVERSION = 0x91,
  GETID = 0x92,
  GETSERIAL = 0x94,
  GETTWORK = 0xA0,       // elapsed time (hh,mm,ss)
  GETHORIZONTAL = 0xA1,  // distance, 2 bytes + units
  GETCALORIES = 0xA3,    // 2 bytes kcal
  GETSPEED = 0xA5,       // 2 bytes, 0.1 km/h
  GETCADENCE = 0xA7,     // 2 bytes rpm/spm
  GETGRADE = 0xA8,       // 2 bytes, signed 0.1 %
  GETHRCUR = 0xB0,       // 1 byte bpm
  GETPOWER = 0xB4,       // 2 bytes watts
  // Long SETs (verify against console before relying on these)
  SETSPEED = 0x26,
  SETGRADE = 0x28,
  SETGEAR = 0x29,
  SETPOWER = 0x34,
};

uint8_t xorChecksum(const uint8_t* data, size_t len);
std::vector<uint8_t> stuff(const std::vector<uint8_t>& data);
std::vector<uint8_t> unstuff(const std::vector<uint8_t>& data, bool& ok);

// Wrap a payload (opcodes+data, no framing) into a complete CSAFE frame.
std::vector<uint8_t> buildFrame(const std::vector<uint8_t>& payload,
                                bool extended = false);

// Parse one exact frame [start .. end]; ok=false on any integrity problem.
// Returns the unstuffed payload (checksum stripped).
std::vector<uint8_t> parseFrame(const std::vector<uint8_t>& frame, bool& ok);

// Standard polling payload used by the telemetry loop.
std::vector<uint8_t> buildTelemetryPayload();

// Streaming reader: feed bytes; appends any complete payloads to `out`.
// Self-delimited by the END byte, so junk between frames is tolerated.
class FrameReader {
 public:
  void feed(uint8_t b, std::vector<std::vector<uint8_t>>& out);
  void reset() { buf_.clear(); }

 private:
  std::vector<uint8_t> buf_;
};

}  // namespace csafe
