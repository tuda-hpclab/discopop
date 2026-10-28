#include <stdio.h>

int g1, g2;

int f(int n) {
  int s = 0;
  for (int i = 0; i < n * 100; i++) s += i % 7;
  return s;
}

void put(int *out, int n) {
  *out = f(n);
}

int show(int *p, int *q) {
  return *p + *q;
}

// tasks write through pointer parameters, main reads the results after h returned
void h(int *r1, int *r2, int k, int n) {
  put(r1, k);
  put(r2, n + 1);
}

void setg1(int v) {
  g1 = f(v);
}

void setg2(int v) {
  g2 = f(v);
}

// tasks write globals, main reads them after h2 returned
void h2(int k, int n) {
  setg1(k);
  setg2(n + 1);
}

// tasks write locals, a callee reads them after the tasks (the join is inside of the function)
int h3(int k, int n) {
  int a, b;
  put(&a, k);
  put(&b, n + 1);
  return show(&a, &b);
}

// reads and writes of its own after h returned: no dependence of the tasks
int control(int x) {
  int local = 0;
  for (int i = 0; i < x; i++) local += i;
  return local;
}

int main() {
  int a, b;
  h(&a, &b, 40, 50);
  int c = control(10);
  h2(40, 50);
  printf("%d %d %d %d\n", a + b, g1 + g2, c, h3(40, 50));
  return 0;
}
