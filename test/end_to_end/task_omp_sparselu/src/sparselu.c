#include <stdio.h>
#include <stdlib.h>

#define NB 3  // blocks per dimension
#define BS 2  // block size

float *new_block(int fill) {
  float *b = malloc(BS * BS * sizeof(float));
  for (int i = 0; i < BS * BS; i++) b[i] = fill ? (i % 3) + 1 + fill : 0;
  return b;
}

void genmat(float **M) {
  for (int ii = 0; ii < NB; ii++)
    for (int jj = 0; jj < NB; jj++) M[ii * NB + jj] = (ii == jj || ii == 0 || jj == 0) ? new_block(ii + jj + 4) : NULL;
}

void lu0(float *diag) {
  for (int k = 0; k < BS; k++)
    for (int i = k + 1; i < BS; i++) {
      diag[i * BS + k] = diag[i * BS + k] / diag[k * BS + k];
      for (int j = k + 1; j < BS; j++) diag[i * BS + j] -= diag[i * BS + k] * diag[k * BS + j];
    }
}

void bdiv(float *diag, float *row) {
  for (int i = 0; i < BS; i++)
    for (int k = 0; k < BS; k++) {
      row[i * BS + k] = row[i * BS + k] / diag[k * BS + k];
      for (int j = k + 1; j < BS; j++) row[i * BS + j] -= row[i * BS + k] * diag[k * BS + j];
    }
}

void bmod(float *row, float *col, float *inner) {
  for (int i = 0; i < BS; i++)
    for (int j = 0; j < BS; j++)
      for (int k = 0; k < BS; k++) inner[i * BS + j] -= row[i * BS + k] * col[k * BS + j];
}

void fwd(float *diag, float *col) {
  for (int j = 0; j < BS; j++)
    for (int k = 0; k < BS; k++)
      for (int i = k + 1; i < BS; i++) col[i * BS + j] -= diag[i * BS + k] * col[k * BS + j];
}

void sparselu(float **BENCH) {
  int ii, jj, kk;
  for (kk = 0; kk < NB; kk++) {
    lu0(BENCH[kk * NB + kk]);
    for (jj = kk + 1; jj < NB; jj++)
      if (BENCH[kk * NB + jj] != NULL)
        // omp-tasks/sparselu/sparselu_single/sparselu.c:229 (task untied firstprivate(kk, jj) shared(BENCH))
        fwd(BENCH[kk * NB + kk], BENCH[kk * NB + jj]);
    for (ii = kk + 1; ii < NB; ii++)
      if (BENCH[ii * NB + kk] != NULL)
        // omp-tasks/sparselu/sparselu_single/sparselu.c:235 (task untied firstprivate(kk, ii) shared(BENCH))
        bdiv(BENCH[kk * NB + kk], BENCH[ii * NB + kk]);
    // omp-tasks/sparselu/sparselu_single/sparselu.c:240 (taskwait)

    for (ii = kk + 1; ii < NB; ii++)
      if (BENCH[ii * NB + kk] != NULL)
        for (jj = kk + 1; jj < NB; jj++)
          if (BENCH[kk * NB + jj] != NULL) {
            // omp-tasks/sparselu/sparselu_single/sparselu.c:246 (task untied firstprivate(kk, jj, ii) shared(BENCH))
            if (BENCH[ii * NB + jj] == NULL) BENCH[ii * NB + jj] = new_block(0);
            bmod(BENCH[ii * NB + kk], BENCH[kk * NB + jj], BENCH[ii * NB + jj]);
          }
    // omp-tasks/sparselu/sparselu_single/sparselu.c:252 (taskwait)
  }
}

int main() {
  float *BENCH[NB * NB];
  genmat(BENCH);
  sparselu(BENCH);
  float sum = 0;
  for (int i = 0; i < NB * NB; i++)
    if (BENCH[i] != NULL)
      for (int e = 0; e < BS * BS; e++) sum += BENCH[i][e];
  printf("%f\n", sum);
  return 0;
}
