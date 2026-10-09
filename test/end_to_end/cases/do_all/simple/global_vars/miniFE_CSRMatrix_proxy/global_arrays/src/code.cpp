#include <stdio.h>
#include <stdlib.h>
#include <vector>

#define N 1000

int rows[N];
int row_offsets[N];

struct CSRMatrix {
  CSRMatrix() {}

  ~CSRMatrix() {}

  void prepare(unsigned nrows) {
    for (unsigned i = 0; i < nrows; ++i) {
      rows[i] = 0;
      row_offsets[i] = 0;
    }
  }
};

int main(int argc, const char *argv[]) {
  int n = N;
  CSRMatrix mat = CSRMatrix();
  mat.prepare(n);
  return 0;
}
