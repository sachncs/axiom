// Standalone differential stress test: run under ASan/UBSan, independently of
// Python.
#include "store.hpp"

#include <iostream>
#include <random>
#include <set>
#include <utility>

void require(bool condition, const char *message) {
  if (!condition)
    throw std::runtime_error(message);
}

using Edge = std::pair<uint32_t, uint32_t>;

void audit(const axiom::Store &graph, const std::set<Edge> &reference) {
  require(graph.check(), "native invariant audit failed");
  require(graph.count == reference.size(), "edge count differs from reference");
  for (uint32_t u = 0; u < graph.n; ++u) {
    const auto row = graph.row(u);
    uint32_t expected = 0;
    for (uint32_t v = 0; v < graph.n; ++v) {
      bool present = reference.count(std::minmax(u, v));
      require(graph.has(u, v) == present, "membership differs from reference");
      expected += present;
    }
    require(row.size() == expected, "row degree differs from reference");
  }
}

int main() {
  try {
    axiom::Store graph(128, 16 * 1024 * 1024);
    std::set<Edge> reference;
    std::mt19937 random(599);
    for (unsigned batch = 0; batch < 1000; ++batch) {
      auto original = reference;
      const uint64_t version = graph.version;
      const auto indexed = graph.indexed;
      const uint64_t token = graph.begin();
      for (unsigned step = 0; step < 200; ++step) {
        uint32_t u = random() % graph.n, v = random() % graph.n;
        if (step % 4 == 0)
          u = batch % 8; // skewed hubs and index crossings
        Edge edge = std::minmax(u, v);
        if (random() & 1) {
          bool expected = u != v && reference.insert(edge).second;
          require(graph.add(u, v) == expected, "insert result differs");
        } else {
          bool expected = reference.erase(edge);
          require(graph.remove(u, v) == expected, "delete result differs");
        }
      }
      audit(graph, reference);
      if (batch % 3) {
        graph.rollback(token);
        reference = original;
        require(graph.version == version, "rollback changed logical version");
        require(graph.indexed == indexed, "rollback changed row indexing");
      } else {
        graph.commit(token);
      }
      audit(graph, reference);
      if (batch % 100 == 0) {
        auto compact = graph.compact();
        audit(*compact, reference);
        require(compact->version == graph.version,
                "compaction changed version");
        graph = std::move(*compact);
      }
    }
    std::cout
        << "200000 mixed edits: differential audits and rollback passed\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
