#include <stdio.h>
#include <stdlib.h>

void allowing_doall(double *tmp, int i) { int z = i + tmp[0]; }

void foo(double *tmp2, int i2) { allowing_doall(tmp2, i2); }

int main(int argc, const char *argv[]) {
  static int n = 1000;
  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // DOALL
  x[0] = 42;
  for (int i = 1; i < n; ++i) {
    x[i] = 1.0;
    foo(x, i);
  }
  free(x);
  return 0;
}
