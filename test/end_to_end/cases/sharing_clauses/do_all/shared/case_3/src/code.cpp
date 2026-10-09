#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 50000;

  double *Arr = (double *) malloc(n*sizeof(double));
  Arr[0] = 1;
  Arr[1] = 2;
  Arr[2] = 3;

  // DO-ALL shared(Arr)
  for (int i = 0; i < n; i++) {
    int x = Arr[0] + Arr[1] + Arr[2];
  }
}
