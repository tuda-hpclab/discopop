#include <stdio.h>
int g_depth = 0;
int rec(int n) {
  if (n == 0) { g_depth += 1; return 0; }
  return 1 + rec(n - 1);
}
int main() {
  int s = 0;
  for (int i = 0; i < 3; ++i) {
    s += rec(2);
  }
  printf("%d\n", s);
  return 0;
}
