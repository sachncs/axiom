// Standalone reference/differential qualification of the non-durable native
// core.
#define AXIOM_TESTING
#include "engine.hpp"

#include <iostream>
#include <random>
#include <set>
#include <utility>

using Edge = std::pair<uint32_t, uint32_t>;

namespace axiom {
struct Inspector {
  static void corruptFreeSummary(Engine &engine) {
    engine.freeVertices.words[1][0] |= uint64_t(1) << 63;
  }
  static uint32_t freeSearch(Engine &engine, uint32_t vertex) {
    return engine.available(vertex);
  }
  static void corruptPublishedIndex(Engine &engine, uint32_t vertex) {
    engine.firstWrite.set(vertex, 12345, engine.limit);
  }
  static void corruptPartner(Engine &engine, uint32_t vertex,
                             uint32_t partner) {
    engine.partners[vertex] = partner;
  }
};
} // namespace axiom

void require(bool value, const char *message) {
  if (!value)
    throw std::runtime_error(message);
}

class Reference {
public:
  std::set<Edge> edges;
  std::vector<uint32_t> partners;
  explicit Reference(uint32_t n) : partners(n, axiom::none) {}

  void rematch(uint32_t u) {
    if (partners[u] != axiom::none)
      return;
    for (uint32_t v = 0; v < partners.size(); ++v)
      if (v != u && partners[v] == axiom::none &&
          edges.count(std::minmax(u, v))) {
        partners[u] = v;
        partners[v] = u;
        return;
      }
  }

  bool edit(uint32_t u, uint32_t v, bool adding) {
    if (u == v)
      return false;
    if (v < u)
      std::swap(u, v);
    Edge edge{u, v};
    if (adding) {
      if (!edges.insert(edge).second)
        return false;
      if (partners[u] == axiom::none && partners[v] == axiom::none) {
        partners[u] = v;
        partners[v] = u;
      }
    } else {
      if (!edges.erase(edge))
        return false;
      if (partners[u] == v) {
        partners[u] = partners[v] = axiom::none;
        rematch(u);
        rematch(v);
      }
    }
    return true;
  }
};

void audit(const axiom::Engine &engine, const Reference &reference) {
  require(engine.check(), "native engine audit failed");
  require(engine.graph().count == reference.edges.size(),
          "graph count differs");
  uint64_t endpoints = 0;
  for (uint32_t u = 0; u < engine.graph().n; ++u) {
    require(engine.partner(u) == reference.partners[u],
            "deterministic partner differs");
    endpoints += engine.partner(u) != axiom::none;
    uint64_t degree = 0;
    for (uint32_t v = 0; v < engine.graph().n; ++v) {
      bool exists = reference.edges.count(std::minmax(u, v));
      require(engine.graph().has(u, v) == exists, "graph edge differs");
      if (exists) {
        ++degree;
        require(reference.partners[u] != axiom::none ||
                    reference.partners[v] != axiom::none,
                "reference matching is not maximal");
      }
    }
    require(engine.graph().degrees[u] == degree, "degree differs");
  }
  require(endpoints == 2 * engine.size(), "matching count differs");
  require(engine.allocated() <= engine.budget(),
          "engine exceeds native budget");
}

int main() {
  try {
    for (uint32_t n : {0u, 1u, 63u, 64u, 65u, 4095u, 4096u, 4097u, 262145u}) {
      axiom::FreeIndex index(n);
      std::vector<uint32_t> partners(n, axiom::none);
      index.build(partners);
      require(index.allocated() == axiom::FreeIndex::base(n),
              "free index bytes differ");
      for (uint32_t u = 0; u < n; u += 3) {
        partners[u] = 0;
        index.set(u, false);
      }
      require(index.check(partners), "free index independent audit failed");
      uint32_t previous = axiom::none;
      uint64_t found = 0;
      for (uint32_t u = index.next(); u != axiom::none; u = index.next(u + 1)) {
        require(u < n && u % 3 && (previous == axiom::none || u > previous),
                "free index iteration differs");
        previous = u;
        ++found;
      }
      require(found == index.count(), "free index enumeration count differs");
      for (uint32_t u = 0; u < n; ++u)
        require(index.valid(u, partners[u] == axiom::none),
                "free index path differs");
    }
    axiom::FreeIndex wide(16777217);
    wide.set(16777216, true);
    require(wide.next() == 16777216 && wide.next(16777217) == axiom::none,
            "deep free summary addressing failed");
    wide.set(16777216, false);
    require(wide.next() == axiom::none && wide.count() == 0,
            "deep free summary clearing failed");
    axiom::Engine badFree(96);
    badFree.ring();
    for (uint32_t v = 3; v <= 78; ++v)
      badFree.insert(0, v);
    axiom::Inspector::corruptFreeSummary(badFree);
    require(!badFree.check(), "corrupt free summary passed independent audit");
    try {
      axiom::Inspector::freeSearch(badFree, 0);
      throw std::runtime_error("corrupt summary did not reject search");
    } catch (const axiom::FreeIndexError &) {
    }
    const auto edgesBefore = badFree.graph().count;
    try {
      badFree.remove(0, 1);
      throw std::runtime_error("corrupt free index did not abort mutation");
    } catch (const axiom::FreeIndexError &) {
    }
    require(badFree.graph().poisoned && !badFree.graph().active &&
                badFree.graph().count == edgesBefore,
            "corrupt free index did not roll back and poison");
    axiom::Engine engine(96, 16 * 1024 * 1024);
    Reference reference(96);
    std::mt19937 random(599);
    for (unsigned batch = 0; batch < 1000; ++batch) {
      Reference original = reference;
      uint64_t version = engine.graph().version;
      uint64_t token = engine.begin();
      for (unsigned step = 0; step < 100; ++step) {
        uint32_t u = random() % 96, v = random() % 96;
        if (step % 3 == 0)
          u = batch % 8;
        bool adding = random() & 1;
        bool changed = reference.edit(u, v, adding);
        require((adding ? engine.insert(u, v) : engine.remove(u, v)) == changed,
                "mutation outcome differs");
        for (uint32_t vertex = 0; vertex < 96; ++vertex) {
          auto published = engine.committedPartner(vertex);
          require(published.first == version &&
                      published.second == original.partners[vertex],
                  "private mutation exposed unpublished partner/version");
        }
      }
      audit(engine, reference);
      if (batch % 3) {
        engine.rollback(token);
        reference = original;
        require(engine.graph().version == version,
                "rollback changed logical version");
      } else
        engine.commit(token);
      audit(engine, reference);
      if (batch % 100 == 0) {
        std::vector<char> checkpoint(engine.snapshotSize());
        engine.snapshot(checkpoint.data(), checkpoint.size());
        auto restored = axiom::Engine::restore(
            checkpoint.data(), checkpoint.size(), engine.budget());
        audit(*restored, reference);
        for (uint32_t vertex = 0; vertex < 96; ++vertex)
          require(restored->committedPartner(vertex) ==
                      engine.committedPartner(vertex),
                  "checkpoint changed published partner view");
        require(restored->graph().version == engine.graph().version,
                "checkpoint changed logical version");
        std::vector<char> repeated(restored->snapshotSize());
        restored->snapshot(repeated.data(), repeated.size());
        require(checkpoint == repeated,
                "checkpoint changed adjacency order/state");
      }
    }
    // A budget that admits metadata but no partner undo cannot partly mutate.
    axiom::Engine corruptIndex(4);
    corruptIndex.insert(0, 1);
    axiom::Inspector::corruptPublishedIndex(corruptIndex, 0);
    require(!corruptIndex.check(), "corrupt published index passed full audit");
    try {
      corruptIndex.committedPartner(0);
      throw std::runtime_error("corrupt published view served data");
    } catch (const axiom::CertificateError &) {
    }
    require(corruptIndex.graph().poisoned,
            "corrupt published view did not poison");
    axiom::Engine probe(4);
    axiom::Engine tight(4, probe.allocated());
    try {
      tight.insert(0, 1);
      throw std::runtime_error("tight budget unexpectedly accepted an edit");
    } catch (const std::length_error &) {
    }
    require(tight.check() && tight.size() == 0 && tight.graph().count == 0 &&
                tight.graph().version == 0 && !tight.graph().active,
            "budget failure changed graph/matching state");
    // Invalid input within a batch aborts all earlier graph and partner writes.
    auto token = engine.begin();
    engine.remove(0, 1);
    try {
      engine.insert(96, 0);
      throw std::runtime_error("invalid vertex unexpectedly accepted");
    } catch (const std::invalid_argument &) {
    }
    audit(engine, reference);
    require(!engine.graph().active, "failed batch remained active");
    try {
      engine.commit(token);
      throw std::runtime_error("aborted token unexpectedly committed");
    } catch (const std::logic_error &) {
    }
    axiom::Engine ring(129);
    ring.ring(16);
    require(ring.check() && ring.graph().count == 129 * 16 && ring.size() == 64,
            "high-degree ring initialization failed");
    std::vector<char> checkpoint(ring.snapshotSize());
    ring.snapshot(checkpoint.data(), checkpoint.size());
    for (unsigned trial = 0; trial < 2000; ++trial) {
      auto altered = checkpoint;
      for (unsigned flip = 0; flip < 1 + trial % 4; ++flip) {
        size_t position = random() % altered.size();
        altered[position] ^= static_cast<char>(1U << (random() % 8));
      }
      try {
        auto candidate =
            axiom::Engine::restore(altered.data(), altered.size(), 4 << 20);
        require(candidate->check(),
                "accepted corrupt checkpoint failed full audit");
      } catch (const std::invalid_argument &) {
      } catch (const std::length_error &) {
      }
    }
    axiom::Engine badCheckpoint(4);
    badCheckpoint.insert(0, 1);
    axiom::Inspector::corruptPartner(badCheckpoint, 0, 2);
    std::vector<char> invalid(badCheckpoint.snapshotSize());
    try {
      badCheckpoint.snapshot(invalid.data(), invalid.size());
      throw std::runtime_error("checkpoint exported invalid partner state");
    } catch (const axiom::CertificateError &) {
    }
    require(badCheckpoint.graph().poisoned &&
                badCheckpoint.graph().version == 1,
            "invalid checkpoint export did not fail-stop without mutation");
    axiom::Engine damaged(4);
    damaged.insert(0, 1);
    axiom::Inspector::corruptPartner(damaged, 0, 2);
    require(!damaged.check(), "independent audit missed partner corruption");
    try {
      damaged.insert(0, 3);
      throw std::runtime_error("dependency corruption unexpectedly committed");
    } catch (const axiom::CertificateError &) {
    }
    require(damaged.graph().poisoned && !damaged.graph().active,
            "certificate failure did not enter fail-stop state");
    require(!damaged.graph().has(0, 3) && damaged.graph().version == 1,
            "certificate failure did not roll back graph edit");
    try {
      damaged.partner(0);
      throw std::runtime_error("poisoned engine exposed partner state");
    } catch (const std::logic_error &) {
    }
    std::cout << "100000 edits: deterministic matching, maximality, budget and "
                 "batch rollback passed\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
