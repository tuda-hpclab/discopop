#include <stdio.h>
int g_x = 0;
int leaf(int v) { g_x += v; return g_x; }
int main() {
  int s = 0;
  for (int i = 0; i < 4; ++i) {
    for (int j = 0; j < 3; ++j) {
      s += leaf(i * j);
    }
  }
  printf("%d\n", s);
  return 0;
}
