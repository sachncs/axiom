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

void ownerAudit() {
  axiom::BlockOwners empty(0);
  require(empty.complete() && empty.bytes() == 0 && !empty.claim(0),
          "empty ownership map differs");
  axiom::BlockOwners owners(130);
  for (uint32_t block = 0; block < 130; ++block)
    require(owners.claim(block), "ownership bit was not initially clear");
  require(!owners.claim(0) && !owners.claim(64) && !owners.claim(130),
          "duplicate or out-of-range block ownership was accepted");
  require(owners.complete() && owners.bytes() >= 24 && owners.bytes() % 8 == 0,
          "ownership bitmap tail mask or byte accounting differs");
  axiom::BlockOwners missing(130);
  for (uint32_t block = 0; block < 129; ++block)
    missing.claim(block);
  require(!missing.complete(), "unowned block passed bitmap audit");
  axiom::Store duplicate(4, 1 << 20);
  duplicate.add(0, 1);
  duplicate.heads[2] = duplicate.heads[0];
  duplicate.tails[2] = duplicate.tails[0];
  duplicate.degrees[2] = 1;
  require(!duplicate.check(), "shared block ownership passed storage audit");
}

int main() {
  try {
    ownerAudit();
    // Cross the degree-128 index boundary and require exact row-index rollback.
    axiom::Store boundary(257, 1 << 20);
    for (uint32_t vertex = 1; vertex < 128; ++vertex)
      boundary.add(0, vertex);
    require(!boundary.indexed[0] && boundary.index.count == 0,
            "moderate row unexpectedly indexed");
    auto token = boundary.begin();
    boundary.add(0, 128);
    boundary.add(0, 129);
    boundary.remove(0, 1);
    require(boundary.indexed[0] && boundary.index.count == 128,
            "hub promotion lost its membership index");
    boundary.rollback(token);
    require(!boundary.indexed[0] && boundary.index.count == 0 &&
                boundary.degrees[0] == 127 && boundary.has(0, 1) &&
                !boundary.has(0, 128) && boundary.check(),
            "promotion rollback changed exact index/graph state");
    boundary.add(0, 128);
    require(boundary.indexed[0] && boundary.check(),
            "promotion after rollback failed");
    axiom::Store graph(256, 16 * 1024 * 1024);
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
