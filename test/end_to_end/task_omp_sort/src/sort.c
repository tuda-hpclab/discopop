#include <stdio.h>

#define N 16
#define SORT_CUTOFF 8
#define MERGE_CUTOFF 6

typedef long ELM;

ELM arr[N], tmpArr[N];

void seqsort(ELM *low, long size) {
  for (long i = 1; i < size; i++) {
    ELM v = low[i];
    long j = i - 1;
    while (j >= 0 && low[j] > v) {
      low[j + 1] = low[j];
      j--;
    }
    low[j + 1] = v;
  }
}

void seqmerge(ELM *low1, ELM *high1, ELM *low2, ELM *high2, ELM *lowdest) {
  while (low1 <= high1 && low2 <= high2) *lowdest++ = (*low1 <= *low2) ? *low1++ : *low2++;
  while (low1 <= high1) *lowdest++ = *low1++;
  while (low2 <= high2) *lowdest++ = *low2++;
}

ELM *binsplit(ELM val, ELM *low, ELM *high) {
  while (low <= high && *low < val) low++;
  return low - 1;
}

void cilkmerge(ELM *low1, ELM *high1, ELM *low2, ELM *high2, ELM *lowdest) {
  ELM *split1, *split2, *t;
  long lowsize;
  if (high2 - low2 > high1 - low1) {
    t = low1; low1 = low2; low2 = t;
    t = high1; high1 = high2; high2 = t;
  }
  if (high2 < low2) {
    while (low1 <= high1) *lowdest++ = *low1++;
    return;
  }
  if (high2 - low2 < MERGE_CUTOFF) {
    seqmerge(low1, high1, low2, high2, lowdest);
    return;
  }
  split1 = ((high1 - low1 + 1) / 2) + low1;
  split2 = binsplit(*split1, low2, high2);
  lowsize = split1 - low1 + split2 - low2;
  *(lowdest + lowsize + 1) = *split1;
  // omp-tasks/sort/sort.c:348 (task)
  cilkmerge(low1, split1 - 1, low2, split2, lowdest);
  // omp-tasks/sort/sort.c:350 (task)
  cilkmerge(split1 + 1, high1, split2 + 1, high2, lowdest + lowsize + 2);
  // omp-tasks/sort/sort.c:353 (taskwait)
  return;
}

void cilksort(ELM *low, ELM *tmp, long size) {
  long quarter = size / 4;
  ELM *A, *B, *C, *D, *tmpA, *tmpC;
  if (size < SORT_CUTOFF) {
    seqsort(low, size);
    return;
  }
  A = low;
  tmpA = tmp;
  B = A + quarter;
  C = B + quarter;
  tmpC = tmpA + 2 * quarter;
  D = C + quarter;
  // omp-tasks/sort/sort.c:384 (task)
  cilksort(A, tmpA, quarter);
  // omp-tasks/sort/sort.c:386 (task)
  cilksort(B, tmpA + quarter, quarter);
  // omp-tasks/sort/sort.c:388 (task)
  cilksort(C, tmpC, quarter);
  // omp-tasks/sort/sort.c:390 (task)
  cilksort(D, tmpC + quarter, size - 3 * quarter);
  // omp-tasks/sort/sort.c:392 (taskwait)
  // omp-tasks/sort/sort.c:394 (task)
  cilkmerge(A, A + quarter - 1, B, B + quarter - 1, tmpA);
  // omp-tasks/sort/sort.c:396 (task)
  cilkmerge(C, C + quarter - 1, D, low + size - 1, tmpC);
  // omp-tasks/sort/sort.c:398 (taskwait)
  cilkmerge(tmpA, tmpC - 1, tmpC, tmpA + size - 1, A);
}

int main() {
  unsigned s = 12345;
  for (int i = 0; i < N; i++) {
    s = s * 1103515245u + 12345u;
    arr[i] = (s >> 8) % 1000;
  }
  cilksort(arr, tmpArr, N);
  for (int i = 1; i < N; i++)
    if (arr[i - 1] > arr[i]) {
      printf("unsorted\n");
      return 1;
    }
  printf("%ld %ld\n", arr[0], arr[N - 1]);
  return 0;
}
