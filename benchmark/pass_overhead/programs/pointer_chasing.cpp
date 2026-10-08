/*
 * This file is part of the DiscoPoP software
 * (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */

// BENCHMARK: Linked list construction and traversal
// Accesses are scattered across many small memory regions, which stresses the
// memory region lookup rather than the access counting itself.

#include <cstdint>
#include <cstdio>

static constexpr int kNodes = 20000;
static constexpr int kTraversals = 400;

struct Node {
  std::int64_t payload;
  Node *next;
};

int main() {
  Node *head = nullptr;
  for (int i = 0; i < kNodes; ++i) {
    Node *node = new Node;
    node->payload = (i * 13) % 257;
    node->next = head;
    head = node;
  }

  std::int64_t checksum = 0;
  for (int traversal = 0; traversal < kTraversals; ++traversal) {
    for (Node *current = head; current != nullptr; current = current->next) {
      checksum += current->payload;
    }
  }

  while (head != nullptr) {
    Node *next = head->next;
    delete head;
    head = next;
  }

  printf("checksum: %lld\n", static_cast<long long>(checksum));
  return 0;
}
