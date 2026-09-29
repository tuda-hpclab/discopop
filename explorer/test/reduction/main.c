#include <stdio.h>

int simpleLoop(int n) {
  int sum = 0;
  for (int i = 0; i < n; i++) {
    sum += i;
  }
  return sum;
}

int main() {
  int res = simpleLoop(10);

  printf("%d\n", res);

  return 0;
}
