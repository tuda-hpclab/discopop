#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 1000;
  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  // DOALL
  for (int i = 0; i < n; ++i) {
    x[i] = i;
  }
  double sum = 0;
  // REDUCTION
  for(int i = 0; i < n; ++i){
    sum += x[i];
  }
  free(x);
  return 0;
}
