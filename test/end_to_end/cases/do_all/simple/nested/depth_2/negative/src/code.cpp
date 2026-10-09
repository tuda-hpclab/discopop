#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 1000;
  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // NOT DOALL
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    double *tmp = x;
    // DOALL
    for (int j = 0; j < 10; j++) {
      tmp[j] = i + tmp[j];
    }
  }
  free(x);
  return 0;
}
