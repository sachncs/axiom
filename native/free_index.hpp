#pragma once

#include "store.hpp"
#include <array>

namespace axiom {

class FreeIndexError : public std::logic_error {
public:
  using std::logic_error::logic_error;
};

// Derived partner metadata, not another graph or a published reader snapshot.
// Six bitmap levels cover the complete uint32 vertex universe. All mutation,
// rebuild and ordered iteration are allocation-free after construction.
class FreeIndex {
#ifdef AXIOM_TESTING
  friend struct Inspector;
#endif
  std::array<std::vector<uint64_t>, 6> words;
  unsigned depth = 0;
  uint32_t universe;
  uint64_t freeCount = 0;

  static unsigned first(uint64_t value) noexcept {
    unsigned result = 0;
    if (!(value & 0xffffffffULL)) {
      result += 32;
      value >>= 32;
    }
    if (!(value & 0xffffULL)) {
      result += 16;
      value >>= 16;
    }
    if (!(value & 0xffULL)) {
      result += 8;
      value >>= 8;
    }
    if (!(value & 0xfULL)) {
      result += 4;
      value >>= 4;
    }
    if (!(value & 3ULL)) {
      result += 2;
      value >>= 2;
    }
    if (!(value & 1ULL))
      ++result;
    return result;
  }

  uint64_t find(unsigned level, uint64_t start) const {
    uint64_t word = start / 64;
    if (word >= words[level].size())
      return vacant;
    uint64_t mask = words[level][word] & (~uint64_t(0) << (start % 64));
    if (mask)
      return word * 64 + first(mask);
    if (level + 1 == depth)
      return vacant;
    word = find(level + 1, word + 1);
    if (word == vacant)
      return vacant;
    if (word >= words[level].size() || !words[level][word])
      throw FreeIndexError("free bitmap summary points to an invalid child");
    return word * 64 + first(words[level][word]);
  }

public:
  explicit FreeIndex(uint32_t n) : universe(n) {
    uint64_t size = n;
    while (size) {
      size = (size + 63) / 64;
      words[depth++].resize(static_cast<size_t>(size));
      if (size == 1)
        break;
    }
  }

  static uint64_t base(uint32_t n) noexcept {
    uint64_t size = n, bytes = 0;
    while (size) {
      size = (size + 63) / 64;
      bytes += size * sizeof(uint64_t);
      if (size == 1)
        break;
    }
    return bytes;
  }

  uint64_t allocated() const noexcept {
    uint64_t bytes = 0;
    for (const auto &level : words)
      bytes += level.capacity() * sizeof(uint64_t);
    return bytes;
  }
  uint64_t count() const noexcept { return freeCount; }
  uint32_t next(uint32_t start = 0) const {
    if (!depth || start >= universe)
      return none;
    uint64_t result = find(0, start);
    if (result != vacant && result >= universe)
      throw FreeIndexError("free bitmap contains an out-of-universe vertex");
    return result >= none ? none : static_cast<uint32_t>(result);
  }

  void set(uint32_t vertex, bool value) noexcept {
    uint64_t bit = uint64_t(1) << (vertex % 64);
    bool old = (words[0][vertex / 64] & bit) != 0;
    freeCount += int(value) - int(old);
    uint64_t index = vertex;
    for (unsigned level = 0; level < depth; ++level) {
      uint64_t word = index / 64, mask = uint64_t(1) << (index % 64);
      if (value)
        words[level][word] |= mask;
      else
        words[level][word] &= ~mask;
      value = words[level][word] != 0;
      index = word;
    }
  }

  bool valid(uint32_t vertex, bool value) const noexcept {
    uint64_t index = vertex;
    for (unsigned level = 0; level < depth; ++level) {
      uint64_t word = index / 64, mask = uint64_t(1) << (index % 64);
      if (((words[level][word] & mask) != 0) != value)
        return false;
      value = words[level][word] != 0;
      index = word;
    }
    return true;
  }

  void build(const std::vector<uint32_t> &partners) noexcept {
    freeCount = 0;
    for (auto &level : words)
      std::fill(level.begin(), level.end(), 0);
    for (size_t u = 0; u < partners.size(); ++u)
      if (partners[u] == none) {
        words[0][u / 64] |= uint64_t(1) << (u % 64);
        ++freeCount;
      }
    for (unsigned level = 1; level < depth; ++level)
      for (size_t i = 0; i < words[level - 1].size(); ++i)
        if (words[level - 1][i])
          words[level][i / 64] |= uint64_t(1) << (i % 64);
  }

  bool check(const std::vector<uint32_t> &partners) const noexcept {
    if (partners.size() != universe)
      return false;
    uint64_t size = universe;
    unsigned expectedDepth = 0;
    for (unsigned level = 0; level < words.size(); ++level) {
      size = size ? (size + 63) / 64 : 0;
      if (words[level].size() != size)
        return false;
      if (size)
        expectedDepth = level + 1;
      if (size == 1)
        size = 0;
    }
    if (expectedDepth != depth)
      return false;
    uint64_t counted = 0;
    for (unsigned level = 0; level < depth; ++level)
      for (size_t word = 0; word < words[level].size(); ++word) {
        uint64_t expected = 0;
        const size_t size = level ? words[level - 1].size() : partners.size();
        for (size_t i = word * 64; i < std::min(size, word * 64 + 64); ++i) {
          bool value = level ? words[level - 1][i] != 0 : partners[i] == none;
          if (value)
            expected |= uint64_t(1) << (i % 64);
          if (!level)
            counted += value;
        }
        if (words[level][word] != expected)
          return false;
      }
    return counted == freeCount;
  }
};

} // namespace axiom
