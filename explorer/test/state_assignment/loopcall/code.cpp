#include <stdio.h>
int g_acc = 0;
void fill(int *p, int n) {
  for (int k = 0; k < n; ++k) {
    p[k] = k + g_acc;
  }
}
int use(int *p) { g_acc += p[1]; return g_acc; }
int main() {
  int buf[8];
  int s = 0;
  for (int i = 0; i < 5; ++i) {
    fill(buf, 8);
    s += use(buf);
  }
  s += use(buf);
  printf("%d\n", s);
  return 0;
}
