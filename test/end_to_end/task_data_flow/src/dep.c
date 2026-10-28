#include <stdio.h>

int f(int n) {
  int s = 0;
  for (int i = 0; i < n * 100; i++) s += i % 7;
  return s;
}

int h(int k, int n) {
  int a, b;
  a = f(k);        // line 11
  b = f(n + 1);    // line 12
  return a + b;    // line 13
}

int main() {
  printf("%d\n", h(40, 50));
  return 0;
}
