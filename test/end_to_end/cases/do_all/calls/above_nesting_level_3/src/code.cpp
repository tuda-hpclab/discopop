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
  static int n = 4000;
  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // DOALL
  for (int i = 0; i < n; i++) {
    x[i] = 1.0;
  }
  for (int k = 0; k < 20; k++) {
    for (int j = 0; j < 20; j++) {
      for (int i = 0; i < n / (20 * 20); ++i) {
        int sum = allowing_doall(x + k * (n / 20) + j * (n / (20 * 20)) + i, (n / (20 * 20)) - i);
      }
    }
  }

  free(x);
  return 0;
}
