#include <stdio.h>
#include <string.h>

#define N 3
#define NS 3

struct cell {
  int top, bot, lhs, rhs;
  int next;
};

static int MIN_AREA = 1000;

static int starts(int id, int shape, int *nws) {
  for (int j = 0; j < NS; j++) nws[j] = id + shape + j;
  return NS;
}

static int lay_down(int id, int *board, struct cell *cells) {
  if (cells[id].bot > 14) return 0;
  board[id] = cells[id].bot + cells[id].rhs;
  return 1;
}

/* omp-tasks/floorplan/floorplan.c, variant IF_CUTOFF (add_cell with if clause) */
static int add_cell(int id, int footprint, int *BOARD, struct cell *CELLS, int level) {
  int i, j, nn, area, nnc, nnl;
  int board[N + 1];
  int nws[NS];
  nnc = nnl = 0;
  for (i = 0; i < 2; i++) {
    nn = starts(id, i, nws);
    nnl += nn;
    for (j = 0; j < nn; j++) {
      /* task: floorplan.c:289, private(board, area) */
      {
        struct cell cells[N + 1];
        memcpy(cells, CELLS, sizeof(struct cell) * (N + 1));
        cells[id].top = nws[j];
        cells[id].bot = cells[id].top + i + 1;
        cells[id].rhs = cells[id].bot + j;
        memcpy(board, BOARD, sizeof(int) * (N + 1));
        if (lay_down(id, board, cells)) {
          area = footprint + cells[id].bot + cells[id].rhs;
          if (cells[id].next == 0) {
            if (area < MIN_AREA) MIN_AREA = area;
          } else if (area < MIN_AREA) {
            nnc += add_cell(cells[id].next, area, board, cells, level + 1);
          }
        }
      }
    }
  }
  // taskwait: floorplan.c:344
  return nnc + nnl;
}

int main() {
  struct cell cells[N + 1];
  int board[N + 1];
  memset(cells, 0, sizeof(cells));
  memset(board, 0, sizeof(board));
  for (int i = 1; i < N; i++) cells[i].next = i + 1;
  printf("%d %d\n", add_cell(1, 0, board, cells, 0), MIN_AREA);
  return 0;
}
