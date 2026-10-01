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
    }
    // A budget that admits metadata but no partner undo cannot partly mutate.
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
