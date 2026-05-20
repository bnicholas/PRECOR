#include "csafe.h"

namespace csafe {

static bool isReserved(uint8_t b) {
  return b == STD_START || b == EXT_START || b == END || b == ESCAPE;
}

uint8_t xorChecksum(const uint8_t* data, size_t len) {
  uint8_t c = 0;
  for (size_t i = 0; i < len; ++i) c ^= data[i];
  return c;
}

std::vector<uint8_t> stuff(const std::vector<uint8_t>& data) {
  std::vector<uint8_t> out;
  out.reserve(data.size());
  for (uint8_t b : data) {
    if (isReserved(b)) {
      out.push_back(ESCAPE);
      out.push_back(b - 0xF0);
    } else {
      out.push_back(b);
    }
  }
  return out;
}

std::vector<uint8_t> unstuff(const std::vector<uint8_t>& data, bool& ok) {
  std::vector<uint8_t> out;
  ok = true;
  for (size_t i = 0; i < data.size(); ++i) {
    if (data[i] == ESCAPE) {
      if (i + 1 >= data.size()) {
        ok = false;
        return out;
      }
      uint8_t n = data[++i];
      if (n > 0x03) {
        ok = false;
        return out;
      }
      out.push_back(0xF0 + n);
    } else {
      out.push_back(data[i]);
    }
  }
  return out;
}

std::vector<uint8_t> buildFrame(const std::vector<uint8_t>& payload,
                                bool extended) {
  std::vector<uint8_t> body = payload;
  body.push_back(xorChecksum(payload.data(), payload.size()));
  std::vector<uint8_t> stuffed = stuff(body);

  std::vector<uint8_t> frame;
  frame.reserve(stuffed.size() + 2);
  frame.push_back(extended ? EXT_START : STD_START);
  frame.insert(frame.end(), stuffed.begin(), stuffed.end());
  frame.push_back(END);
  return frame;
}

std::vector<uint8_t> parseFrame(const std::vector<uint8_t>& frame, bool& ok) {
  ok = false;
  std::vector<uint8_t> empty;
  if (frame.size() < 3) return empty;
  if (frame.front() != STD_START && frame.front() != EXT_START) return empty;
  if (frame.back() != END) return empty;

  std::vector<uint8_t> inner(frame.begin() + 1, frame.end() - 1);
  bool uok = false;
  std::vector<uint8_t> unstuffed = unstuff(inner, uok);
  if (!uok || unstuffed.empty()) return empty;

  uint8_t checksum = unstuffed.back();
  std::vector<uint8_t> payload(unstuffed.begin(), unstuffed.end() - 1);
  if (xorChecksum(payload.data(), payload.size()) != checksum) return empty;

  ok = true;
  return payload;
}

std::vector<uint8_t> buildTelemetryPayload() {
  return {GETSTATUS, GETTWORK,  GETHORIZONTAL, GETCALORIES,
          GETSPEED,  GETCADENCE, GETHRCUR,      GETPOWER};
}

void FrameReader::feed(uint8_t b, std::vector<std::vector<uint8_t>>& out) {
  buf_.push_back(b);
  if (b != END) return;

  // Trim anything before the start byte, then try to parse.
  size_t start = 0;
  bool found = false;
  for (size_t i = 0; i < buf_.size(); ++i) {
    if (buf_[i] == STD_START || buf_[i] == EXT_START) {
      start = i;
      found = true;
      break;
    }
  }
  if (found) {
    std::vector<uint8_t> raw(buf_.begin() + start, buf_.end());
    bool ok = false;
    std::vector<uint8_t> payload = parseFrame(raw, ok);
    if (ok) out.push_back(payload);
  }
  buf_.clear();
}

}  // namespace csafe
