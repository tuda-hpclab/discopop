#include <stdio.h>
// a loop inside a recursive function: the profiler cuts the callpath at the recursive call,
// while the TaskGraph inlines the recursion up to its call depth limit
int g_acc = 0;
int g_arr[4] = {0, 0, 0, 0};
void rec(int n) {
  for (int i = 0; i < 4; ++i) {
    g_acc += i;
    g_arr[i] += n;
  }
  if (n > 0) {
    rec(n - 1);
  }
}
int main() {
  for (int t = 0; t < 2; ++t) {
    rec(3);
  }
  printf("%d %d\n", g_acc, g_arr[2]);
  return 0;
}
