#include <stdio.h>

int f(int i) {
  if (i < 100000 / 2) {
    return i + 100000 / 2;
  } else {
    return i;
  }
}

int g(int i) { return i; }

int main() {
  int N = 100000;
  int Arr[100000];

  // DOALL
  for (int i = 0; i < N; i++) {
    Arr[i] = 0;
  }

  long w = 0;

  // NO REDUCTION, NO DOALL
  for (int i = 0; i < N; i++) {
    w += Arr[g(i)];
    Arr[f(i)] = 1;
  }
}
