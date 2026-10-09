#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 100;
  double *x = (double *)malloc(n * sizeof(double));
  // NOT DOALL
  for (int i = 1; i < n; ++i) {
    x[i] = 1.0;
    int z = i + x[i - 1];
    x[i] = z + 2;
  }
  free(x);
  return 0;
}
