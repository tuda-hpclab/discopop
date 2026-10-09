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

    for (MINIFE_GLOBAL_ORDINAL i = 0; i < nrows; ++i) {
      rows[i] = 0;
      row_offsets[i] = 0;
    }
  }
};

int main(int argc, const char *argv[]) {
  int n = 1000;
  CSRMatrix<MINIFE_GLOBAL_ORDINAL> mat = CSRMatrix<MINIFE_GLOBAL_ORDINAL>();
  mat.reserve_space(n);
  return 0;
}
