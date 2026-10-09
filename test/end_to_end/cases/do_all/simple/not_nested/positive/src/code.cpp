#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 1000;
  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // DOALL
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    double *tmp = x;
    int z = i + tmp[i];
    tmp[i] = z + 2;
  }
  free(x);
  return 0;
}
