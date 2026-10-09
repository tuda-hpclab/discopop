#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  // proxy for "compute matrix vector product" in
  // miniFE.src.SparseMatrix_functions.
  int n = 10;

  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
  }

  for (int row = 0; row < n; ++row) {
    int sum = 0; // stack variable

    for (int j = 0; j < n; j++) {
      sum += row * j;
    }

    x[row] = sum;
  }

  free(x);

  return 0;
}
