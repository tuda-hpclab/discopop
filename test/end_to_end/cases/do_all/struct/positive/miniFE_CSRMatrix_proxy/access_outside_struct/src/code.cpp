#include <stdio.h>
#include <stdlib.h>
#include <vector>

#define MINIFE_GLOBAL_ORDINAL int

template <typename GlobalOrdinal>

struct CSRMatrix {
  CSRMatrix() : rows(), row_offsets() {}

  ~CSRMatrix() {}

  std::vector<GlobalOrdinal> rows;
  std::vector<GlobalOrdinal> row_offsets;

  void reserve_space(unsigned nrows) {
    rows.resize(nrows);
    row_offsets.resize(nrows + 1);
  }
};

int main(int argc, const char *argv[]) {
  int n = 1000;
  CSRMatrix<MINIFE_GLOBAL_ORDINAL> mat = CSRMatrix<MINIFE_GLOBAL_ORDINAL>();

  mat.reserve_space(n);
  for (MINIFE_GLOBAL_ORDINAL i = 0; i < n; ++i) {
    mat.rows[i] = 0;
    mat.row_offsets[i] = 0;
  }
  return 0;
}
