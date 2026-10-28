#include <cstdio>

struct Node {
  int height;
  int state;
};

// A loop whose body calls the function again: 15 executions of the loop, two iterations each, recursion depth 4.
long walk_uniform(int depth) {
  long sum = 0;
  for (int i = 0; i < 2; i++) {  // LOOP:walk_uniform
    sum += (depth < 3) ? walk_uniform(depth + 1) : 1;
  }
  return sum;
}

// The same loop executions without recursion: 15 calls, two iterations each.
long plain_uniform() {
  long sum = 0;
  for (int i = 0; i < 2; i++) {  // LOOP:plain_uniform
    sum += 1;
  }
  return sum;
}

// The root runs three iterations, the three callees run none.
long walk_zero(int depth, int n) {
  long sum = 0;
  for (int i = 0; i < n; i++) {  // LOOP:walk_zero
    sum += walk_zero(depth + 1, 0);
  }
  return sum;
}

// The same loop executions without recursion: one with three iterations, three with none.
long plain_zero(int n) {
  long sum = 0;
  for (int i = 0; i < n; i++) {  // LOOP:plain_zero
    sum += 1;
  }
  return sum;
}

// Iterations are independent: every iteration writes its own element of nodes, the callee reads it through parent.
long fill(int depth, Node *parent, int n) {
  Node nodes[3];
  long partial[3];
  long total = 1;
  for (int i = 0; i < n; i++) {  // LOOP:fill
    Node *p = &nodes[i];
    p->height = parent->height + 1;
    p->state = parent->state * 3 + i;
    partial[i] = (depth < 2) ? fill(depth + 1, p, 3) : 1;
  }
  for (int i = 0; i < n; i++) {
    total += partial[i];
  }
  return total;
}

int main() {
  long result = walk_uniform(0);
  for (int k = 0; k < 15; k++) {
    result += plain_uniform();
  }
  result += walk_zero(0, 3);
  result += plain_zero(3);
  for (int k = 0; k < 3; k++) {
    result += plain_zero(0);
  }
  Node root = {0, 7};
  result += fill(0, &root, 3);
  printf("%ld\n", result);
  return 0;
}
