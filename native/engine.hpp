#pragma once

#include "store.hpp"

namespace axiom {

struct PartnerUndo {
  uint32_t vertex, previous, expected;
};

class CertificateError : public std::logic_error {
public:
  using std::logic_error::logic_error;
};

// Explicit production algorithm; this is not the paper's coloring/hierarchy
// engine. Private storage and partner writes establish the locality certificate
// boundary.
class Engine {
#ifdef AXIOM_TESTING
  friend struct Inspector;
#endif
  uint64_t limit;
  Store storage;
  std::vector<uint32_t> partners;
  std::vector<PartnerUndo> writes;
  uint64_t matched = 0, savedMatched = 0;

  static uint64_t overhead() { return sizeof(Engine) - sizeof(Store); }

  static uint64_t graphBudget(uint32_t vertices, uint64_t budget) {
    uint64_t extra = overhead() + uint64_t(vertices) * sizeof(uint32_t);
    if (budget < extra || Store::base(vertices) > budget - extra)
      throw std::length_error("engine metadata exceeds native budget");
    return budget - extra;
  }

  void rebudget() {
    uint64_t extra = overhead() +
                     uint64_t(partners.capacity()) * sizeof(uint32_t) +
                     uint64_t(writes.capacity()) * sizeof(PartnerUndo);
    if (extra > limit || storage.allocated() > limit - extra)
      throw std::length_error("engine native allocation exceeds budget");
    storage.budget = limit - extra;
  }

  void reserveWrites(uint64_t needed) {
    if (needed <= writes.capacity())
      return;
    uint64_t maximum = (limit - allocated()) / sizeof(PartnerUndo);
    if (needed > maximum)
      throw std::length_error("partner journal peak exceeds native budget");
    uint64_t target = std::min(
        maximum, std::max(needed, std::max(uint64_t(8),
                                           uint64_t(writes.capacity()) * 2)));
    std::vector<PartnerUndo> candidate;
    candidate.reserve(static_cast<size_t>(target));
    if (allocated() + uint64_t(candidate.capacity()) * sizeof(PartnerUndo) >
        limit)
      throw std::length_error(
          "partner journal allocator peak exceeds native budget");
    candidate.assign(writes.begin(), writes.end());
    writes.swap(candidate);
    rebudget();
  }

  void write(uint32_t vertex, uint32_t value) noexcept {
    writes.push_back(PartnerUndo{vertex, partners[vertex], value});
    partners[vertex] = value;
  }

  void pair(uint32_t u, uint32_t v) noexcept {
    write(u, v);
    write(v, u);
    ++matched;
  }

  uint32_t available(uint32_t u) const noexcept {
    uint32_t best = none;
    for (uint32_t b = storage.heads[u]; b != none; b = storage.blocks[b].next)
      for (uint32_t i = 0; i < storage.blocks[b].used; ++i) {
        uint32_t v = storage.blocks[b].items[i];
        if (partners[v] == none && v < best)
          best = v;
      }
    return best;
  }

  void rematch(uint32_t u) noexcept {
    if (partners[u] != none)
      return;
    uint32_t v = available(u);
    if (v != none)
      pair(u, v);
  }

  bool certified(uint32_t u) const noexcept {
    uint32_t v = partners[u];
    if (v == none)
      return available(u) == none;
    return v < storage.n && v != u && partners[v] == u && storage.has(u, v);
  }

  void token(uint64_t value) const {
    storage.healthy();
    if (!storage.active || storage.serial != value)
      throw std::logic_error("invalid or stale engine transaction token");
  }

  bool edit(uint32_t u, uint32_t v, bool adding) {
    storage.healthy();
    bool own = !storage.active;
    uint64_t transaction = own ? begin() : storage.serial;
    try {
      if (u >= storage.n || v >= storage.n)
        throw std::invalid_argument("vertex out of range");
      if (v < u)
        std::swap(u, v);
      if (u == v || storage.has(u, v) == adding) {
        if (own)
          commit(transaction);
        return false;
      }
      if (storage.version == std::numeric_limits<uint64_t>::max() ||
          storage.epoch == std::numeric_limits<uint64_t>::max())
        throw std::length_error("engine mutation sequence exhausted");
      const uint64_t version = storage.version, edges = storage.count;
      const uint64_t priorMatched = matched;
      const uint32_t left = storage.degrees[u], right = storage.degrees[v];
      const size_t first = writes.size();
      // At most six partner writes: unpair two endpoints, then pair each once.
      const bool repairs = adding ? partners[u] == none && partners[v] == none
                                  : partners[u] == v;
      if (repairs)
        reserveWrites(writes.size() + (adding ? 2 : 6));
      if (adding) {
        storage.add(u, v);
        if (repairs)
          pair(u, v);
      } else {
        storage.remove(u, v);
        if (repairs) {
          write(u, none);
          write(v, none);
          --matched;
          rematch(u);
          rematch(v);
        }
      }
      const int delta = adding ? 1 : -1;
      if (storage.count != (adding ? edges + 1 : edges - 1) ||
          storage.version != version + 1 ||
          storage.degrees[u] != uint64_t(left) + delta ||
          storage.degrees[v] != uint64_t(right) + delta ||
          storage.has(u, v) != adding || storage.has(v, u) != adding ||
          !certified(u) || !certified(v) || matched > storage.n / 2)
        throw CertificateError("native engine local certificate failed");
      int64_t endpointDelta = 0;
      for (size_t i = first; i < writes.size(); ++i) {
        endpointDelta +=
            int(writes[i].expected != none) - int(writes[i].previous != none);
        if (!certified(writes[i].vertex))
          throw CertificateError(
              "native partner dependency certificate failed");
      }
      if (endpointDelta % 2 ||
          int64_t(matched) != int64_t(priorMatched) + endpointDelta / 2)
        throw CertificateError(
            "native matching count delta certificate failed");
      if (own)
        commit(transaction);
      return true;
    } catch (const CertificateError &) {
      rollback(transaction);
      storage.poisoned = true;
      throw;
    } catch (...) {
      rollback(transaction);
      throw;
    }
  }

public:
  explicit Engine(uint32_t vertices, uint64_t budget = defaultBudget)
      : limit(budget), storage(vertices, graphBudget(vertices, budget)),
        partners(vertices, none) {
    rebudget();
  }

  const Store &graph() const { return storage; }
  uint64_t size() const {
    storage.healthy();
    return matched;
  }
  uint32_t partner(uint32_t vertex) const {
    storage.healthy();
    if (vertex >= storage.n)
      throw std::invalid_argument("vertex out of range");
    return partners[vertex];
  }
  uint64_t budget() const { return limit; }
  uint64_t allocated() const {
    return overhead() + storage.allocated() +
           uint64_t(partners.capacity()) * sizeof(uint32_t) +
           uint64_t(writes.capacity()) * sizeof(PartnerUndo);
  }
  uint64_t journal() const {
    return uint64_t(writes.capacity()) * sizeof(PartnerUndo) +
           uint64_t(storage.undo.capacity()) * sizeof(Undo);
  }

  uint64_t begin() {
    storage.healthy();
    uint64_t result = storage.begin();
    writes.clear();
    savedMatched = matched;
    return result;
  }
  void commit(uint64_t value) {
    token(value);
    storage.commit(value);
    writes.clear();
  }
  void rollback(uint64_t value) {
    token(value);
    for (auto it = writes.rbegin(); it != writes.rend(); ++it) {
      if (partners[it->vertex] != it->expected) {
        storage.poisoned = true;
        throw std::logic_error("partner rollback found unexpected state");
      }
      partners[it->vertex] = it->previous;
    }
    storage.rollback(value);
    writes.clear();
    matched = savedMatched;
  }
  bool insert(uint32_t u, uint32_t v) { return edit(u, v, true); }
  bool remove(uint32_t u, uint32_t v) { return edit(u, v, false); }

  bool check() const {
    if (!storage.check() || allocated() > limit)
      return false;
    uint64_t endpoints = 0;
    for (uint32_t u = 0; u < storage.n; ++u) {
      // Independent full audit, not a replay of the local certificate helper.
      uint32_t v = partners[u];
      if (v != none) {
        if (v >= storage.n || v == u || partners[v] != u || !storage.has(u, v))
          return false;
        ++endpoints;
      } else {
        for (uint32_t b = storage.heads[u]; b != none;
             b = storage.blocks[b].next)
          for (uint32_t i = 0; i < storage.blocks[b].used; ++i)
            if (partners[storage.blocks[b].items[i]] == none)
              return false;
      }
    }
    return endpoints == 2 * matched;
  }

  void ring(uint64_t width = 2) {
    storage.healthy();
    auto candidate = storage.ring(width);
    // Include the old graph and old partner array in candidate peak accounting.
    uint64_t extra = uint64_t(storage.n) * sizeof(uint32_t);
    if (allocated() + candidate->allocated() + extra > limit)
      throw std::length_error(
          "engine ring candidate peak exceeds native budget");
    std::vector<uint32_t> next(storage.n, none);
    if (allocated() + candidate->allocated() +
            uint64_t(next.capacity()) * sizeof(uint32_t) >
        limit)
      throw std::length_error(
          "engine ring allocator peak exceeds native budget");
    uint64_t count = 0;
    for (uint32_t u = 0; u < storage.n; ++u) {
      if (next[u] != none)
        continue;
      uint32_t best = none;
      for (uint32_t b = candidate->heads[u]; b != none;
           b = candidate->blocks[b].next)
        for (uint32_t i = 0; i < candidate->blocks[b].used; ++i) {
          uint32_t v = candidate->blocks[b].items[i];
          if (next[v] == none && v < best)
            best = v;
        }
      if (best != none) {
        next[u] = best;
        next[best] = u;
        ++count;
      }
    }
    if (!candidate->check())
      throw std::logic_error("engine ring graph audit failed");
    uint64_t endpoints = 0;
    for (uint32_t u = 0; u < storage.n; ++u) {
      uint32_t v = next[u];
      if (v != none) {
        if (v >= storage.n || next[v] != u || !candidate->has(u, v))
          throw std::logic_error("engine ring partner audit failed");
        ++endpoints;
      } else {
        for (uint32_t b = candidate->heads[u]; b != none;
             b = candidate->blocks[b].next)
          for (uint32_t i = 0; i < candidate->blocks[b].used; ++i)
            if (next[candidate->blocks[b].items[i]] == none)
              throw std::logic_error("engine ring maximality audit failed");
      }
    }
    if (endpoints != 2 * count)
      throw std::logic_error("engine ring matching count audit failed");
    storage = std::move(*candidate);
    partners.swap(next);
    matched = count;
    rebudget();
  }
};

} // namespace axiom
