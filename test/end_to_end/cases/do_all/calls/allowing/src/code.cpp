#include <stdio.h>
#include <stdlib.h>

void allowing_doall(double *tmp, int i) {
  int z = i + tmp[i];
  tmp[i] = z + 2;
}

int main(int argc, const char *argv[]) {
  static int n = 1000;
  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // DOALL
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    allowing_doall(x, i);
  }
  free(x);
  return 0;
}
