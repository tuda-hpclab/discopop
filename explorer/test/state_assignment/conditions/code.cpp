#include <stdio.h>
// condition shapes of miniFE: a chain of `if (a && b) return` blocks sharing the final return
// (imbalance.hpp), and long `||` chains assigned to a bool (box_utils.hpp)
int g_box[3][2] = {{0, 4}, {1, 9}, {2, 3}};
int g_calls = 0;
int pick(int limit) {
  if (g_box[0][1] < limit && g_box[0][1] - g_box[0][0] > 2) {
    g_calls += 1;
    return 0;
  }
  if (g_box[1][1] < limit && g_box[1][1] - g_box[1][0] > 2) {
    g_calls += 2;
    return 1;
  }
  if (g_box[2][1] < limit && g_box[2][1] - g_box[2][0] > 2) {
    g_calls += 3;
    return 2;
  }
  return -1;
}
bool neighbor(int a, int b) {
  bool x = (g_box[a][1] == g_box[b][0]) || (g_box[a][0] == g_box[b][1]) || (g_box[a][0] == g_box[b][0]) ||
           (g_box[a][1] == g_box[b][1]) || (g_box[a][0] > g_box[b][0] && g_box[a][1] < g_box[b][1]) ||
           (g_box[b][0] > g_box[a][0] && g_box[b][1] < g_box[a][1]);
  if (!x) {
    x = (g_box[a][1] == g_box[b][0] - 1) || (g_box[a][0] == g_box[b][1] + 1);
  }
  return x;
}
int main() {
  int s = 0;
  for (int i = 0; i < 4; ++i) {
    s += pick(i * 3);
    s += neighbor(i % 3, (i + 1) % 3) ? 1 : 0;
  }
  printf("%d %d\n", s, g_calls);
  return 0;
}
