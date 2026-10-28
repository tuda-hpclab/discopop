#include <stdio.h>

int fib(int n) {
  if (n < 2) return n;
  int a = fib(n - 1);  // line 5
  int b = fib(n - 2);  // line 6
  return a + b;        // line 7
}

int main() {
  int data[200];
  int sum = 0;
  for (int i = 0; i < 200; i++) data[i] = i * 2;  // a do-all loop, not asked for
  for (int i = 0; i < 200; i++) sum += data[i];   // a reduction, not asked for
  printf("%d %d\n", fib(15), sum);
  return 0;
}
