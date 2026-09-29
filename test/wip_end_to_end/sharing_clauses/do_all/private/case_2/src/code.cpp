#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 50000;

  double *Arr = (double *) malloc(n*sizeof(double));

  // DO-ALL private(Arr)
  for (int i = 0; i < n; i++) {
    Arr[0] = i;
    Arr[1] = i+2;
    Arr[2] = i-4;
    int x = Arr[0] + Arr[1] + Arr[2];
  }
}
