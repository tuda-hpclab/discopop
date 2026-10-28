#include <stdio.h>

int f(int n) {
  int s = 0;
  for (int i = 0; i < n * 100; i++) s += i % 7;
  return s;
}

void store(int *dst, int value) {
  *dst = value;
}

int g(int n) {
  int res[16];
  int total;
  for (int k = 0; k < 16; k++) {
    store(&res[k], f(n + k));  // line 17
  }
  total = res[3] + res[5];  // line 19
  return total;
}

int main() {
  printf("%d\n", g(10));
  return 0;
}
