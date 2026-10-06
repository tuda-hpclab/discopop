#include <stdio.h>
#include <stdlib.h>
int g_q[8] = {1, 2, 3, 4, 5, 6, 7, 8};
int g_sum = 0;
void calc_q(int limit) {
  int idx = -1;
  for (int i = 0; i < 8; ++i) {
    if (g_q[i] > limit) {
      idx = i;
      break;
    }
  }
  if (idx >= 0) {
    exit(3);
  }
  g_sum += limit;
}
void after() { g_sum += 1; }
int main() {
  for (int t = 0; t < 4; ++t) {
    calc_q(100);
    after();
  }
  printf("%d\n", g_sum);
  return 0;
}
