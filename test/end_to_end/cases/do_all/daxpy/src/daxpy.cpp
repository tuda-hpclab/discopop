#include <stdio.h>
#include <stdlib.h>

void daxpy(int n, double a, double *x, double *y) {
  for (int i = 0; i < n; ++i)
    y[i] = a * x[i] + y[i];
}

void foo() {
  for (int i = 0; i < 100; i++) {
    int y = 42 * i;
  }
}

int main(int argc, const char *argv[]) {
  static int n = 10000;
  static double a = 2.0;
  double *x = (double *)malloc(n * sizeof(double));
  double *y = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    y[i] = 2.0;
    foo();
  }
  daxpy(n, a, x, y); // Invoke daxpy kernel
  // Check if all values are 4.0
  double error = 0.0;
  for (int i = 0; i < n; i++) {
    error += y[i] - 4.0;
  }
  printf("Error: %f\n", error);
  free(x);
  free(y);
  return 0;
}
