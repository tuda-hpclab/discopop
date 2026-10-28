#include <stdio.h>
#include <stdlib.h>

#define N 4

// C = A x B for n x n matrices stored with the row widths rc, ra and rb
void multiply_base(double *C, double *A, double *B, int n, int rc, int ra, int rb) {
  for (int i = 0; i < n; i++)
    for (int j = 0; j < n; j++) {
      double s = 0;
      for (int k = 0; k < n; k++) s += A[i * ra + k] * B[k * rb + j];
      C[i * rc + j] = s;
    }
}

void strassen(double *C, double *A, double *B, int n, int rc, int ra, int rb) {
  int q = n / 2;
  if (n <= 2) {
    multiply_base(C, A, B, n, rc, ra, rb);
    return;
  }
  double *A11 = A, *A12 = A + q, *A21 = A + ra * q, *A22 = A21 + q;
  double *B11 = B, *B12 = B + q, *B21 = B + rb * q, *B22 = B21 + q;
  double *C11 = C, *C12 = C + q, *C21 = C + rc * q, *C22 = C21 + q;
  double *S1 = malloc(q * q * sizeof(double)), *S2 = malloc(q * q * sizeof(double));
  double *S3 = malloc(q * q * sizeof(double)), *S4 = malloc(q * q * sizeof(double));
  double *S5 = malloc(q * q * sizeof(double)), *S6 = malloc(q * q * sizeof(double));
  double *S7 = malloc(q * q * sizeof(double)), *S8 = malloc(q * q * sizeof(double));
  double *M2 = malloc(q * q * sizeof(double)), *M5 = malloc(q * q * sizeof(double));
  double *T1 = malloc(q * q * sizeof(double));
  for (int i = 0; i < q; i++)
    for (int j = 0; j < q; j++) {
      int e = i * q + j;
      S1[e] = A21[i * ra + j] + A22[i * ra + j];
      S2[e] = S1[e] - A11[i * ra + j];
      S3[e] = A11[i * ra + j] - A21[i * ra + j];
      S4[e] = A12[i * ra + j] - S2[e];
      S5[e] = B12[i * rb + j] - B11[i * rb + j];
      S6[e] = B22[i * rb + j] - S5[e];
      S7[e] = B22[i * rb + j] - B12[i * rb + j];
      S8[e] = S6[e] - B21[i * rb + j];
    }

  // omp-tasks/strassen/strassen.c:901 (task untied)
  strassen(M2, A11, B11, q, q, ra, rb);
  // omp-tasks/strassen/strassen.c:905 (task untied)
  strassen(M5, S1, S5, q, q, q, q);
  // omp-tasks/strassen/strassen.c:909 (task untied)
  strassen(T1, S2, S6, q, q, q, q);
  // omp-tasks/strassen/strassen.c:913 (task untied)
  strassen(C22, S3, S7, q, rc, q, q);
  // omp-tasks/strassen/strassen.c:917 (task untied)
  strassen(C11, A12, B21, q, rc, ra, rb);
  // omp-tasks/strassen/strassen.c:921 (task untied)
  strassen(C12, S4, B22, q, rc, q, rb);
  // omp-tasks/strassen/strassen.c:925 (task untied)
  strassen(C21, A22, S8, q, rc, ra, q);
  // omp-tasks/strassen/strassen.c:931 (taskwait)

  for (int i = 0; i < q; i++)
    for (int j = 0; j < q; j++) {
      int e = i * q + j, c = i * rc + j;
      C11[c] = C11[c] + M2[e];
      T1[e] = T1[e] + M2[e];
      C12[c] = C12[c] + T1[e] + M5[e];
      C22[c] = C22[c] + T1[e];
      C21[c] = C22[c] - C21[c];
      C22[c] = C22[c] + M5[e];
    }
  free(S1);
  free(S2);
  free(S3);
  free(S4);
  free(S5);
  free(S6);
  free(S7);
  free(S8);
  free(M2);
  free(M5);
  free(T1);
}

int main() {
  double A[N * N], B[N * N], C[N * N];
  for (int i = 0; i < N * N; i++) {
    A[i] = i % 5 + 1;
    B[i] = i % 3 + 1;
  }
  strassen(C, A, B, N, N, N, N);
  printf("%f\n", C[0] + C[N * N - 1]);
  return 0;
}
