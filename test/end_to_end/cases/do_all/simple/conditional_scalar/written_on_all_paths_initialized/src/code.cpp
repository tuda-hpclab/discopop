#include <stdio.h>
#include <stdlib.h>

#define BLOCK 4

// do_all/simple/conditional_scalar/written_on_all_paths with delta initialized before the loop: the
// initial value is never read inside the loop, as every cell writes delta before reading it, so the
// chunk loop is still a do-all loop with delta private
void step(float *result, const float *temp, int n) {
  float delta = 0.0f;
  int chunks_per_row = n / BLOCK;
  int num_chunk = chunks_per_row * chunks_per_row;
  for (int chunk = 0; chunk < num_chunk; ++chunk) {
    int r_start = BLOCK * (chunk / chunks_per_row);
    int c_start = BLOCK * (chunk % chunks_per_row);
    if (r_start == 0 || c_start == 0 || r_start + BLOCK == n || c_start + BLOCK == n) {
      for (int r = r_start; r < r_start + BLOCK; ++r) {
        for (int c = c_start; c < c_start + BLOCK; ++c) {
          if ((r == 0) && (c == 0)) {
            delta = temp[1] - temp[0];
          } else if ((r == n - 1) && (c == n - 1)) {
            delta = temp[r * n + c - 1] - temp[r * n + c];
          } else if (r == 0) {
            delta = temp[c - 1] - temp[c];
          } else if (c == n - 1) {
            delta = temp[(r - 1) * n + c] - temp[r * n + c];
          } else if (r == n - 1) {
            delta = temp[r * n + c - 1] - temp[r * n + c];
          } else if (c == 0) {
            delta = temp[(r - 1) * n] - temp[r * n];
          } else {
            delta = temp[(r - 1) * n + c] - temp[r * n + c];
          }
          result[r * n + c] = temp[r * n + c] + 0.5f * delta;
        }
      }
      continue;
    }
    for (int r = r_start; r < r_start + BLOCK; ++r) {
      for (int c = c_start; c < c_start + BLOCK; ++c) {
        result[r * n + c] = temp[r * n + c] + 0.25f * (temp[(r - 1) * n + c] - temp[r * n + c]);
      }
    }
  }
}

int main(int argc, const char *argv[]) {
  int n = argc > 1 ? atoi(argv[1]) : 16;
  float *temp = (float *)malloc(sizeof(float) * n * n);
  float *result = (float *)malloc(sizeof(float) * n * n);
  for (int i = 0; i < n * n; ++i) {
    temp[i] = (float)(i % 7);
  }
  for (int t = 0; t < 2; ++t) {
    step(result, temp, n);
    float *swap = temp;
    temp = result;
    result = swap;
  }
  printf("%f\n", temp[n * n / 2]);
  free(temp);
  free(result);
  return 0;
}
