#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 50000;
  double *x = (double *)malloc(n * sizeof(double));
  double *y = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    y[i] = 2.0;
  }

  for (int i = 0; i < n; ++i) {
    x[i] = 0.0;
  }

  for (int i = 0; i < n; ++i) {
    y[i] = 1.0;
  }

  for (int i = 0; i < n; ++i) {
    x[i] = x[i] + y[i];
  }
}
