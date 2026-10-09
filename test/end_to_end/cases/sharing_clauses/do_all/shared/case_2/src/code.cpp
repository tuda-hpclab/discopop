#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 50000;

  double *Arr = (double *) malloc(n*sizeof(double));

  int z = 0;

  // DO-ALL private(Arr)
  for (int i = 0; i < n; i++) {
    Arr[i] = i;
    int x = Arr[i];
  }
}
