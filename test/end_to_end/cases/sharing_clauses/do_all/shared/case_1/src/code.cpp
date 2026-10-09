#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 50000;

  double *Arr = (double *) malloc(n*sizeof(double));
  Arr[42] = 123.456;

  int z = 0;

  // DO-ALL shared(Arr) private(z)
  for (int i = 0; i < n; i++) {
    z = Arr[42] + i;
    int x = z;
  }
}
