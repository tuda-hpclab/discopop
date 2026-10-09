#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 50000;
  double *x = (double *)malloc(n * sizeof(double));
  double *y = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // Do-All
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    y[i] = 2.0;
  }

  // Do-All
  for (int i = 0; i < n / 10; i++) {
    // Do-All
    for (int j = 0; j < 10; j++) {
      y[i * 10 + j] = x[i * 10 + j] / 42;
    }
  }
  free(x);
  free(y);
}
