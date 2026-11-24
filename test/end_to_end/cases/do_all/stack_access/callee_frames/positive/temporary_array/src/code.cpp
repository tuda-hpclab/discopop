#include <array>
#include <cstdio>
#include <vector>

struct Node {
  std::array<Node *, 8> children{};
  double weight = 0.0;
};

__attribute__((noinline)) static double sum_up(const double *values, const int count) {
  double sum = 0.0;
  for (int k = 0; k < count; k++) {
    sum += values[k];
  }
  return sum;
}

// returns a copy, like a node cache: the array is a temporary in the frame of the caller
__attribute__((noinline)) static std::array<Node *, 8> get_children(const Node *node) { return node->children; }

// a large local whose address escapes: its stores are profiled, and it occupies the stack memory that the
// temporary array of add_children occupies later in the same iteration
static int accept(const Node *node, const double position, const double criterion) {
  double distances[32];
  for (int k = 0; k < 32; k++) {
    distances[k] = position - node->weight * k;
  }
  const double d = sum_up(distances, 32) / 32.0;
  return (d * d < criterion) ? 1 : 2;
}

static int count_targets(const double position, Node *root, const double criterion) {
  std::vector<Node *> stack;
  const auto add_children = [&stack](const Node *node) {
    const auto &children = get_children(node);
    for (auto *child : children) {
      if (child != nullptr) {
        stack.push_back(child);
      }
    }
  };
  add_children(root);
  int found = 0;
  while (!stack.empty()) {
    Node *node = stack.back();
    stack.pop_back();
    if (accept(node, position, criterion) == 1) {
      found++;
    } else {
      add_children(node);
    }
  }
  return found;
}

int main() {
  std::vector<Node> nodes(73);
  for (std::size_t i = 0; i < nodes.size(); i++) {
    nodes[i].weight = static_cast<double>(i) / 10.0;
  }
  for (std::size_t i = 0; i < 9; i++) {
    for (std::size_t c = 0; c < 8; c++) {
      nodes[i].children[c] = &nodes[8 * i + c + 1];
    }
  }
  const int n = 100;
  std::vector<int> result(n);
  for (int i = 0; i < n; i++) {
    result[i] = count_targets(static_cast<double>(i) / 10.0, &nodes[0], 0.5);
  }
  int sum = 0;
  for (int i = 0; i < n; i++) {
    sum += result[i];
  }
  std::printf("%d\n", sum);
  return 0;
}
