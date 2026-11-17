#include <stdio.h>
#include <stdlib.h>

#define N 2000

// small helper: a candidate for inlining at -O2
static double scale(double v) { return v * 2.0 + 1.0; }

static double sum_array(const double *a, int n) {
  double s = 0.0;
  for (int i = 0; i < n; ++i) {
    s += a[i];
  }
  return s;
}

int main(int argc, const char *argv[]) {
  double *x = (double *)malloc(N * sizeof(double));
  double *y = (double *)malloc(N * sizeof(double));
  double *z = (double *)malloc(N * sizeof(double));

  // do-all
  for (int i = 0; i < N; ++i) {
    x[i] = i * 0.5;
    y[i] = 2.0;
  }

  // do-all with an inlinable call
  for (int i = 0; i < N; ++i) {
    z[i] = scale(x[i]) + y[i];
  }

  // loop carried dependence (recurrence)
  for (int i = 1; i < N; ++i) {
    z[i] = z[i - 1] * 0.5 + x[i];
  }

  // reduction on a local scalar (promoted to a register at -O1 and above)
  double dot = 0.0;
  for (int i = 0; i < N; ++i) {
    dot += x[i] * y[i];
  }

  // reduction inside a callee
  double total = sum_array(z, N);

  printf("%f %f\n", dot, total);
  free(x);
  free(y);
  free(z);
  return 0;
}
