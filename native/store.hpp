#pragma once

#include <algorithm>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <vector>

namespace axiom {
constexpr uint32_t none = std::numeric_limits<uint32_t>::max();
constexpr uint64_t defaultBudget = 1ULL << 30;

struct Block {
  uint32_t next = none;
  uint32_t previous = none;
  uint32_t items[4] = {};
  uint32_t used = 0;
};
static_assert(sizeof(Block) == 28,
              "block accounting must reflect its native layout");

constexpr uint64_t vacant = std::numeric_limits<uint64_t>::max();
constexpr uint64_t removed = vacant - 1;
// Keep moderate rows on a bounded (<128-neighbor) scan. Indexing every row of
// a degree-64 million-vertex ring would otherwise add 2 GiB of hash slots.
// Large hubs still use the membership/location index; certificates are unchanged.
constexpr uint32_t threshold = 128;
struct Slot {
  uint64_t key = vacant;
  uint64_t location = 0;
};
static_assert(sizeof(Slot) == 16,
              "index accounting must reflect its native layout");

class Index {
public:
  std::vector<Slot> slots;
  uint64_t count = 0, tombstones = 0;

  Slot *find(uint64_t key) noexcept {
    if (slots.empty())
      return nullptr;
    size_t mask = slots.size() - 1;
    size_t position = hash(key) & mask;
    for (size_t attempts = 0; attempts < slots.size(); ++attempts) {
      Slot &slot = slots[position];
      if (slot.key == key)
        return &slot;
      if (slot.key == vacant)
        return nullptr;
      position = (position + 1) & mask;
    }
    return nullptr;
  }

  const Slot *find(uint64_t key) const noexcept {
    return const_cast<Index *>(this)->find(key);
  }

  static uint64_t hash(uint64_t key) noexcept {
    key ^= key >> 30;
    key *= 0xbf58476d1ce4e5b9ULL;
    key ^= key >> 27;
    key *= 0x94d049bb133111ebULL;
    return key ^ (key >> 31);
  }

  void insert(uint64_t key, uint64_t location) noexcept {
    size_t mask = slots.size() - 1;
    size_t position = hash(key) & mask;
    for (;;) {
      Slot &slot = slots[position];
      if (slot.key == vacant || slot.key == removed) {
        if (slot.key == removed)
          --tombstones;
        slot = Slot{key, location};
        ++count;
        return;
      }
      position = (position + 1) & mask;
    }
  }

  void erase(uint64_t key) noexcept {
    Slot *slot = find(key);
    slot->key = removed;
    --count;
    ++tombstones;
  }
};

inline uint64_t key(uint32_t u, uint32_t v) noexcept {
  return (uint64_t(u) << 32) | v;
}
inline uint64_t location(uint32_t b, uint32_t i) noexcept {
  return (uint64_t(b) << 32) | i;
}

struct Undo {
  uint32_t u, v;
  bool added, indexedU, indexedV;
};

class Store {
public:
  uint32_t n;
  uint64_t budget;
  uint64_t count = 0;
  uint64_t version = 0;
  uint64_t epoch = 0;
  uint32_t free = none;
  uint32_t spare = 0;
  std::vector<uint32_t> heads, tails, degrees;
  std::vector<uint8_t> indexed;
  std::vector<Block> blocks;
  Index index;
  std::vector<Undo> undo;
  bool active = false, poisoned = false;
  uint64_t serial = 0, savedVersion = 0, savedCount = 0;

  static uint64_t base(uint32_t vertices) {
    return sizeof(Store) +
           uint64_t(vertices) * (sizeof(uint32_t) * 3 + sizeof(uint8_t));
  }

  Store(uint32_t vertices, uint64_t limit) : n(vertices), budget(limit) {
    if (base(n) > budget)
      throw std::length_error("vertex metadata exceeds native budget");
    heads.assign(n, none);
    tails.assign(n, none);
    degrees.assign(n, 0);
    indexed.assign(n, 0);
  }

  uint64_t allocated() const {
    return sizeof(Store) +
           sizeof(uint32_t) * uint64_t(heads.capacity() + tails.capacity() +
                                       degrees.capacity()) +
           indexed.capacity() + sizeof(Block) * uint64_t(blocks.capacity()) +
           sizeof(Slot) * uint64_t(index.slots.capacity()) +
           sizeof(Undo) * uint64_t(undo.capacity());
  }

  void healthy() const {
    if (poisoned)
      throw std::logic_error(
          "native storage is poisoned after a rollback failure");
  }

  uint64_t begin() {
    healthy();
    if (active)
      throw std::logic_error("nested native transactions are not allowed");
    if (serial == std::numeric_limits<uint64_t>::max())
      throw std::length_error("transaction token space exhausted");
    active = true;
    savedVersion = version;
    savedCount = count;
    undo.clear();
    return ++serial;
  }

  void commit(uint64_t token) {
    healthy();
    if (!active || token != serial)
      throw std::logic_error("invalid or stale transaction token");
    undo.clear();
    active = false;
  }

  void reserveUndo() {
    if (!active || undo.size() < undo.capacity())
      return;
    uint64_t maximum = (budget - allocated()) / sizeof(Undo);
    uint64_t needed = undo.size() + 1;
    if (needed > maximum)
      throw std::length_error("transaction journal peak exceeds native budget");
    uint64_t target = std::min(
        maximum,
        std::max(needed, std::max(uint64_t(8), uint64_t(undo.capacity()) * 2)));
    std::vector<Undo> candidate;
    candidate.reserve(static_cast<size_t>(target));
    if (allocated() + sizeof(Undo) * uint64_t(candidate.capacity()) > budget)
      throw std::length_error("journal allocator peak exceeds native budget");
    candidate.assign(undo.begin(), undo.end());
    undo.swap(candidate);
  }

  bool has(uint32_t u, uint32_t v) const {
    if (indexed[u])
      return index.find(key(u, v)) != nullptr;
    for (uint32_t b = heads[u]; b != none; b = blocks[b].next)
      for (uint32_t i = 0; i < blocks[b].used; ++i)
        if (blocks[b].items[i] == v)
          return true;
    return false;
  }

  void reserve(uint64_t needed, bool exact = false) {
    if (needed > none)
      throw std::length_error("native block address space exhausted");
    if (needed <= blocks.capacity())
      return;
    uint64_t maximum = (budget - allocated()) / sizeof(Block);
    if (needed > maximum)
      throw std::length_error("edge growth exceeds native budget");
    uint64_t target =
        exact ? needed
              : std::max(needed,
                         std::min(maximum,
                                  std::max(uint64_t(8),
                                           uint64_t(blocks.capacity()) * 2)));
    std::vector<Block> candidate;
    candidate.reserve(static_cast<size_t>(target));
    if (allocated() + sizeof(Block) * uint64_t(candidate.capacity()) > budget)
      throw std::length_error("allocator growth peak exceeds native budget");
    candidate.assign(blocks.begin(), blocks.end());
    blocks.swap(candidate);
  }

  void prepare(uint32_t u, uint32_t v) {
    uint32_t needed = (degrees[u] % 4 == 0) + (degrees[v] % 4 == 0);
    reserve(uint64_t(blocks.size()) + (needed > spare ? needed - spare : 0));
    uint64_t entries = (indexed[u]                    ? 1
                        : degrees[u] + 1 >= threshold ? degrees[u] + 1
                                                      : 0) +
                       (indexed[v]                    ? 1
                        : degrees[v] + 1 >= threshold ? degrees[v] + 1
                                                      : 0);
    reserveIndex(index.count + entries);
  }

  void reserveIndex(uint64_t needed) {
    uint64_t target = index.slots.size();
    if (needed * 2 <= target && index.tombstones <= target / 3)
      return;
    if (needed == 0 && target == 0)
      return;
    target = std::max(uint64_t(8), target);
    while (target < needed * 2)
      target *= 2;
    if (target > (budget - allocated()) / sizeof(Slot))
      throw std::length_error("index growth peak exceeds native budget");
    Index candidate;
    candidate.slots.resize(static_cast<size_t>(target));
    if (allocated() + sizeof(Slot) * uint64_t(candidate.slots.capacity()) >
        budget)
      throw std::length_error("index allocator peak exceeds native budget");
    for (const Slot &slot : index.slots)
      if (slot.key != vacant && slot.key != removed)
        candidate.insert(slot.key, slot.location);
    index.slots.swap(candidate.slots);
    index.count = candidate.count;
    index.tombstones = 0;
  }

  void activate(uint32_t u) noexcept {
    if (indexed[u])
      return;
    for (uint32_t b = heads[u]; b != none; b = blocks[b].next)
      for (uint32_t i = 0; i < blocks[b].used; ++i)
        index.insert(key(u, blocks[b].items[i]), location(b, i));
    indexed[u] = 1;
  }

  void indexRows() {
    uint64_t entries = 0;
    for (uint32_t u = 0; u < n; ++u)
      if (degrees[u] >= threshold)
        entries += degrees[u];
    reserveIndex(entries);
    for (uint32_t u = 0; u < n; ++u)
      if (degrees[u] >= threshold)
        activate(u);
  }

  uint32_t acquire() noexcept {
    if (free != none) {
      uint32_t b = free;
      free = blocks[b].next;
      --spare;
      blocks[b] = Block{};
      return b;
    }
    uint32_t b = static_cast<uint32_t>(blocks.size());
    blocks.emplace_back(); // capacity was reserved before publication
    return b;
  }

  void append(uint32_t u, uint32_t v) noexcept {
    if (degrees[u] % 4 == 0) {
      uint32_t b = acquire();
      blocks[b].previous = tails[u];
      if (tails[u] == none)
        heads[u] = b;
      else
        blocks[tails[u]].next = b;
      tails[u] = b;
    }
    Block &tail = blocks[tails[u]];
    if (indexed[u])
      index.insert(key(u, v), location(tails[u], tail.used));
    tail.items[tail.used++] = v;
    ++degrees[u];
  }

  bool add(uint32_t u, uint32_t v) {
    healthy();
    if (u == v || has(u, v))
      return false;
    prepare(u, v);
    reserveUndo();
    if (active)
      undo.push_back(Undo{u, v, true, bool(indexed[u]), bool(indexed[v])});
    if (!indexed[u] && degrees[u] + 1 >= threshold)
      activate(u);
    if (!indexed[v] && degrees[v] + 1 >= threshold)
      activate(v);
    append(u, v);
    append(v, u);
    ++count;
    ++version;
    ++epoch;
    return true;
  }

  void erase(uint32_t u, uint32_t v) noexcept {
    uint32_t last = tails[u];
    uint32_t replacement = blocks[last].items[blocks[last].used - 1];
    if (indexed[u]) {
      uint64_t target = index.find(key(u, v))->location;
      blocks[uint32_t(target >> 32)].items[uint32_t(target)] = replacement;
      if (replacement != v)
        index.find(key(u, replacement))->location = target;
      index.erase(key(u, v));
    } else {
      for (uint32_t b = heads[u]; b != none; b = blocks[b].next)
        for (uint32_t i = 0; i < blocks[b].used; ++i)
          if (blocks[b].items[i] == v) {
            blocks[b].items[i] = replacement;
            break;
          }
    }
    --blocks[last].used;
    --degrees[u];
    if (blocks[last].used == 0) {
      uint32_t previous = blocks[last].previous;
      if (previous == none)
        heads[u] = tails[u] = none;
      else {
        blocks[previous].next = none;
        tails[u] = previous;
      }
      blocks[last].next = free;
      free = last;
      ++spare;
    }
    if (!degrees[u])
      indexed[u] = 0;
  }

  bool remove(uint32_t u, uint32_t v) {
    healthy();
    if (u == v || !has(u, v))
      return false;
    reserveUndo();
    if (active)
      undo.push_back(Undo{u, v, false, bool(indexed[u]), bool(indexed[v])});
    erase(u, v);
    erase(v, u);
    --count;
    ++version;
    ++epoch;
    return true;
  }

  void rollback(uint64_t token) {
    healthy();
    if (!active || token != serial)
      throw std::logic_error("invalid or stale transaction token");
    if (!undo.empty())
      ++epoch;
    active = false;
    for (auto it = undo.rbegin(); it != undo.rend(); ++it) {
      if (has(it->u, it->v) != it->added) {
        poisoned = true;
        throw std::logic_error(
            "native rollback found unexpected graph contents");
      }
      if (it->added) {
        erase(it->u, it->v);
        erase(it->v, it->u);
        --count;
      } else {
        append(it->u, it->v);
        append(it->v, it->u);
        ++count;
      }
      restoreIndex(it->u, it->indexedU);
      restoreIndex(it->v, it->indexedV);
    }
    undo.clear();
    if (count != savedCount) {
      poisoned = true;
      throw std::logic_error("native rollback did not restore edge accounting");
    }
    version = savedVersion;
  }

  void restoreIndex(uint32_t u, bool expected) noexcept {
    if (expected) {
      activate(u);
      return;
    }
    if (!indexed[u])
      return;
    for (uint32_t b = heads[u]; b != none; b = blocks[b].next)
      for (uint32_t i = 0; i < blocks[b].used; ++i)
        index.erase(key(u, blocks[b].items[i]));
    indexed[u] = 0;
  }

  std::vector<uint32_t> row(uint32_t u) const {
    std::vector<uint32_t> result;
    result.reserve(degrees[u]);
    for (uint32_t b = heads[u]; b != none; b = blocks[b].next)
      for (uint32_t i = 0; i < blocks[b].used; ++i)
        result.push_back(blocks[b].items[i]);
    std::sort(result.begin(), result.end());
    return result;
  }

  bool check() const {
    if (poisoned)
      return false;
    std::vector<uint8_t> ownership(blocks.size(), 0);
    uint64_t entries = 0;
    uint64_t indexedEntries = 0;
    std::vector<uint32_t> neighbors;
    for (uint32_t u = 0; u < n; ++u) {
      uint32_t degree = 0, last = none;
      neighbors.clear();
      for (uint32_t b = heads[u]; b != none; b = blocks[b].next) {
        if (b >= blocks.size() || ownership[b] || !blocks[b].used ||
            blocks[b].used > 4)
          return false;
        ownership[b] = 1;
        if (blocks[b].previous != last)
          return false;
        if (blocks[b].next != none && blocks[b].used != 4)
          return false;
        for (uint32_t i = 0; i < blocks[b].used; ++i) {
          uint32_t v = blocks[b].items[i];
          if (v >= n || v == u || !has(v, u))
            return false;
          neighbors.push_back(v);
          if (indexed[u]) {
            const Slot *slot = index.find(key(u, v));
            if (!slot || slot->location != location(b, i))
              return false;
          }
        }
        degree += blocks[b].used;
        last = b;
      }
      if (degree != degrees[u] || last != tails[u])
        return false;
      std::sort(neighbors.begin(), neighbors.end());
      if (std::adjacent_find(neighbors.begin(), neighbors.end()) !=
          neighbors.end())
        return false;
      if (!indexed[u] && degree >= threshold)
        return false;
      entries += degree;
      if (indexed[u])
        indexedEntries += degree;
    }
    uint32_t unused = 0;
    for (uint32_t b = free; b != none; b = blocks[b].next) {
      if (b >= blocks.size() || ownership[b] || blocks[b].used)
        return false;
      ownership[b] = 1;
      ++unused;
    }
    uint64_t occupied = 0, tombstones = 0;
    for (const Slot &slot : index.slots) {
      occupied += slot.key != vacant && slot.key != removed;
      tombstones += slot.key == removed;
    }
    return unused == spare && entries == 2 * count && allocated() <= budget &&
           occupied == index.count && tombstones == index.tombstones &&
           indexedEntries == index.count &&
           std::find(ownership.begin(), ownership.end(), 0) == ownership.end();
  }

  std::unique_ptr<Store> compact() const {
    healthy();
    if (active)
      throw std::logic_error(
          "compaction is not allowed during a native transaction");
    uint64_t live = blocks.size() - spare;
    if (allocated() + base(n) + live * sizeof(Block) > budget)
      throw std::length_error("compaction peak exceeds native budget");
    auto result = std::make_unique<Store>(n, budget - allocated());
    result->reserve(live, true);
    for (uint32_t u = 0; u < n; ++u)
      for (uint32_t b = heads[u]; b != none; b = blocks[b].next)
        for (uint32_t i = 0; i < blocks[b].used; ++i)
          result->append(u, blocks[b].items[i]);
    result->count = count;
    result->version = version;
    result->epoch = epoch;
    result->serial = serial;
    result->indexRows();
    result->budget = budget;
    return result;
  }

  std::unique_ptr<Store> ring(uint64_t width) const {
    healthy();
    if (active)
      throw std::logic_error(
          "ring publication is not allowed during a native transaction");
    if (count)
      throw std::invalid_argument("ring construction requires an empty graph");
    if (width && (n < 3 || width > (uint64_t(n) - 1) / 2))
      throw std::invalid_argument(
          "ring width must be less than half the vertex universe");
    uint64_t blockCount = uint64_t(n) * ((2 * width + 3) / 4);
    if (allocated() + base(n) + blockCount * sizeof(Block) > budget)
      throw std::length_error("ring construction peak exceeds native budget");
    auto candidate = std::make_unique<Store>(n, budget - allocated());
    candidate->reserve(blockCount, true);
    for (uint32_t u = 0; u < n; ++u)
      for (uint64_t distance = 1; distance <= width; ++distance) {
        candidate->append(u,
                          static_cast<uint32_t>((uint64_t(u) + distance) % n));
        candidate->append(
            u, static_cast<uint32_t>((uint64_t(u) + n - distance) % n));
      }
    candidate->count = uint64_t(n) * width;
    candidate->version = version + (candidate->count ? 1 : 0);
    candidate->epoch = epoch + (candidate->count ? 1 : 0);
    candidate->serial = serial;
    candidate->indexRows();
    candidate->budget = budget;
    return candidate;
  }
};

} // namespace axiom
