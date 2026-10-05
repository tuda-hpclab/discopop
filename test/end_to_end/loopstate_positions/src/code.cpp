#include <cstdio>
#include <cstdlib>

// mirrors IntegrateStressForElems: a loop nested in an else inside a loop,
// followed by a loop nest under an if
void kernel(int n, int threads, double* a, double* b) {
  double local[8];
  for (int k = 0; k < n; ++k) {
    a[k] = k * 0.5;
    if (threads > 1) {
      b[k] += a[k];
    } else {
      for (int l = 0; l < 8; ++l) {
        local[l] = a[k] + l;
        b[k] += local[l];
      }
    }
  }
  if (threads > 1) {
    for (int g = 0; g < n; ++g) {
      for (int i = 0; i < 4; ++i) {
        b[g] += i;
      }
    }
  }
}

// sibling loops in if / else
double siblings(int n, double* a) {
  double s = 0;
  if (n > 5) {
    for (int i = 0; i < n; ++i) {
      s += a[i];
    }
  } else {
    for (int j = 0; j < n; ++j) {
      s -= a[j];
    }
  }
  for (int m = 0; m < n; ++m) {
    for (int q = 0; q < 3; ++q) {
      s += m * q;
    }
  }
  return s;
}

// an early return placed before an inner loop
int early_return(int n, int* err, double* a) {
  for (int i = 0; i < n; ++i) {
    if (err[i]) {
      return i;
    }
    for (int j = 0; j < 4; ++j) {
      a[i] += j;
    }
  }
  return -1;
}

int main(int argc, char** argv) {
  int n = 10;
  int threads = argc > 5 ? 2 : 1;
  double* a = (double*)calloc(n, sizeof(double));
  double* b = (double*)calloc(n, sizeof(double));
  kernel(n, threads, a, b);
  double s = siblings(n, a);
  int* err = (int*)calloc(n, sizeof(int));
  err[7] = 1;
  s += early_return(n, err, a);
  free(err);
  printf("%f %f\n", b[3], s);
  free(a);
  free(b);
  return 0;
}
