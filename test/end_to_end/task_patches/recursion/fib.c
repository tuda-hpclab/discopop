#include <stdio.h>

long long fib(int n) {
  long long x, y;
  if (n < 2) return n;
  x = fib(n - 1);  // line 6
  y = fib(n - 2);  // line 7
  return x + y;
}

int main() {
  long long res;
  res = fib(20);  // line 13
  printf("%lld\n", res);
  return 0;
}
