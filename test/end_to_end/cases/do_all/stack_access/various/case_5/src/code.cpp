#include <stdio.h>
#include <stdlib.h>

int f(int t) {
  t = t * 42 + t - 2;
  return t;
}

int main(int argc, const char *argv[]) {
  static int n = 100;
  double *x = (double *)malloc(n * sizeof(double));
  double *y = (double *)malloc(n * sizeof(double));

  for (int i = 0; i < n; i++) {
    int s = 0;
    for (int j = 0; j < n; j++) {
      s = f(j);
      x[j] = s;
    }
    for (int j = 0; j < n; j++) {
      s = f(j);
      y[j] = s;
    }
  }

  free(x);
  free(y);
  return 0;
}
