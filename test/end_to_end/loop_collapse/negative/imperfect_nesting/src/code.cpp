#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 5000;
  double *x = (double *)malloc(n * sizeof(double));
  double *y = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // Do-All
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    y[i] = 2.0;
  }

  // Do-All. Both loops of this nest are parallelizable, but they are not perfectly
  // nested: the assignment below sits in the outer loop body next to the inner loop.
  // Collapsing the two would execute it once per combined iteration instead of once
  // per iteration of the outer loop.
  for (int a = 0; a < n / 10; a++) {
    x[a * 10] = 0.0;
    // Do-All
    for (int b = 0; b < 10; b++) {
      y[a * 10 + b] = x[a * 10 + b] * 2.0;
    }
  }

  printf("%f %f\n", x[0], y[0]);
  free(x);
  free(y);
}
