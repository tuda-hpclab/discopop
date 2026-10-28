#include <stdio.h>

int d;

int f(int n) {
  int s = 0;
  for (int i = 0; i < n * 100; i++) s += i % 7;
  return s;
}

int h(int k, int n) {
  d = f(k);        // line 12
  d = f(n + 1);    // line 13
  return d;        // line 14
}

int main() {
  printf("%d\n", h(40, 50));
  return 0;
}
