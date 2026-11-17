#include <stdio.h>
#include <stdlib.h>

#define N 1000

// The two branches differ in the loop they contain. Which one is compiled depends on whether __OPTIMIZE__ is defined,
// i.e. on the optimization level; the instrumented code and the AST export must agree on it.
int main(int argc, const char *argv[]) {
  double *a = (double *)malloc(N * sizeof(double));
  double *b = (double *)malloc(N * sizeof(double));
  for (int i = 0; i < N; ++i) {
    a[i] = i;
    b[i] = 1.0;
  }
#ifdef __OPTIMIZE__
  for (int i = 0; i < N; ++i) {
    b[i] = a[i] * 2.0;
  }
#else
  for (int i = 1; i < N; ++i) {
    b[i] = b[i - 1] + a[i];
  }
#endif
  printf("%f\n", b[N - 1]);
  free(a);
  free(b);
  return 0;
}
