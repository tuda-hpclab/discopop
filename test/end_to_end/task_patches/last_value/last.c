#include <stdio.h>

int f(int n) {
  int s = 0;
  for (int i = 0; i < n * 100; i++) s += i % 7;
  return s;
}

int g(int n) {
  int last = 0, v, res[16];
  for (int k = 0; k < 16; k++) {
    v = f(n + k);  // line 11
    res[k] = v;
    last = v;
  }
  return last + res[3];
}

int main() {
  printf("%d\n", g(10));
  return 0;
}
