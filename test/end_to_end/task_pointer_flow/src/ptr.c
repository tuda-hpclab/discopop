#include <stdio.h>

int f(int n) {
  int s = 0;
  for (int i = 0; i < n * 100; i++) s += i % 7;
  return s;
}

void put(int *out, int n) {
  *out = f(n);
}

int h(int k, int n) {
  int a, b;
  put(&a, k);      // line 15
  put(&b, n + 1);  // line 16
  if (a + b > 0) return 1;  // line 17
  return 0;
}

int main() {
  printf("%d\n", h(40, 50));
  return 0;
}
