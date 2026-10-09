/*
#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char* argv[]) {
    static int n = 100;
    double *x = (double *) malloc(n * sizeof(double));
    int y = 0;
    // NOT DOALL
    for(int i = 1; i < n; ++i){
        x[i] = 1.0;
        int z = i + x[i-1];
        x[i] = z + 2;
        if(z % 2 == 0){
            y = y + 1;
        }
    }
    free(x);
return 0;
}
*/

#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 1000;
  double *x = (double *)malloc(n * sizeof(double));
  // Initialize x, y
  int y = 0;
  // NOT DOALL
  for (int i = 0; i < n; ++i) {
    x[i] = 1.0;
    double *tmp = x;
    int z = i + tmp[i];
    tmp[i] = z + 2;
    if (z % 2 == 0) {
      y = y + 1;
    }
  }
  free(x);
  return 0;
}
