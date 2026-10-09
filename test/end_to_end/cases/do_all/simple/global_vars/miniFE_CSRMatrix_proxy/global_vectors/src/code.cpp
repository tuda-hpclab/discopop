#include <stdio.h>
#include <stdlib.h>
#include <vector>

std::vector<int> rows;
std::vector<int> row_offsets;

struct CSRMatrix {
  CSRMatrix() {}

  ~CSRMatrix() {}

  void reserve_space(unsigned nrows) {
    rows.resize(nrows);
    row_offsets.resize(nrows + 1);

    for (unsigned i = 0; i < nrows; ++i) {
      rows[i] = 0;
      row_offsets[i] = 0;
    }
  }
};

int main(int argc, const char *argv[]) {
  int n = 1000;
  CSRMatrix mat = CSRMatrix();
  mat.reserve_space(n);
  return 0;
}
