#include <stdio.h>
#include <stdlib.h>

int allowing_doall(double tmp[], int i) {
  int sum = 0;
  for (int n = 0; n < i; n++) {
    sum = tmp[i];
  }
  return sum;
}

int main(int argc, const char *argv[]) {
  static int n = 1000;
  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // DOALL
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    int sum = allowing_doall(x + i, n - i);
  }
  free(x);
  return 0;
}
