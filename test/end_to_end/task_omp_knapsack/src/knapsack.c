#include <stdio.h>

#define NITEMS 8

struct item {
  int value;
  int weight;
};

int best_so_far = 0;

// omp-tasks/knapsack/knapsack.c:226-246 (knapsack_par)
void knapsack(struct item *e, int c, int n, int v, int *sol, int l) {
  int with, without, best;
  if (c < 0) {
    *sol = -1000000;
    return;
  }
  if (n == 0 || c == 0) {
    *sol = v;
    return;
  }
  // knapsack.c:226-227 task without
  knapsack(e + 1, c, n - 1, v, &without, l + 1);
  // knapsack.c:230-231 task with
  knapsack(e + 1, c - e->weight, n - 1, v + e->value, &with, l + 1);
  // knapsack.c:233 taskwait
  best = with > without ? with : without;
  if (best > best_so_far) best_so_far = best;
  *sol = best;
}

int main() {
  struct item items[NITEMS];
  for (int i = 0; i < NITEMS; i++) {
    items[i].value = 10 + 7 * i % 11;
    items[i].weight = 3 + 5 * i % 7;
  }
  int sol = 0;
  knapsack(items, 15, NITEMS, 0, &sol, 0);
  printf("%d\n", sol);
  return 0;
}
