#include <stdio.h>

int f(int n) {
  int s = 0;
  for (int i = 0; i < n * 100; i++) s += i % 7;
  return s;
}

int g(int n) {
  int sum = 0;
  for (int k = 0; k < 16; k++) {
    sum += f(n + k);  // line 11
  }
  return sum;
}

int main() {
  printf("%d\n", g(10));
  return 0;
}
