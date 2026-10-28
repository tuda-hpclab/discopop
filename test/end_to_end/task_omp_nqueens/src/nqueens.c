#include <stdio.h>
#include <string.h>

#define N 5

int ok(int n, char *a) {
  for (int i = 0; i < n; i++) {
    char p = a[i];
    for (int j = i + 1; j < n; j++) {
      char q = a[j];
      if (q == p || q == p - (j - i) || q == p + (j - i)) return 0;
    }
  }
  return 1;
}

// omp-tasks/nqueens/nqueens.c, IF_CUTOFF variant (nqueens)
void nqueens_if(int n, int j, char *a, int *solutions, int depth) {
  int csols[N];
  if (n == j) {
    *solutions = 1;
    return;
  }
  *solutions = 0;
  memset(csols, 0, sizeof(csols));
  for (int i = 0; i < n; i++) {
    { // nqueens.c:160-172 task
      char b[N];
      memcpy(b, a, j * sizeof(char));
      b[j] = (char) i;
      if (ok(j + 1, b))
        nqueens_if(n, j + 1, b, &csols[i], depth + 1);
    }
  }
  // nqueens.c:175 taskwait
  for (int i = 0; i < n; i++) *solutions += csols[i];
}

// omp-tasks/nqueens/nqueens.c, default variant (nqueens)
void nqueens_plain(int n, int j, char *a, int *solutions, int depth) {
  int csols[N];
  if (n == j) {
    *solutions = 1;
    return;
  }
  *solutions = 0;
  memset(csols, 0, sizeof(csols));
  for (int i = 0; i < n; i++) {
    { // nqueens.c:350-362 task
      char b[N];
      memcpy(b, a, j * sizeof(char));
      b[j] = (char) i;
      if (ok(j + 1, b))
        nqueens_plain(n, j + 1, b, &csols[i], depth);
    }
  }
  // nqueens.c:365 taskwait
  for (int i = 0; i < n; i++) *solutions += csols[i];
}

int main() {
  char a[N];
  int s1 = 0, s2 = 0;
  nqueens_if(N, 0, a, &s1, 0);
  nqueens_plain(N, 0, a, &s2, 0);
  printf("%d %d\n", s1, s2);
  return 0;
}
