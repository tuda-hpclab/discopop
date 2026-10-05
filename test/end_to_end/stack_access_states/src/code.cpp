// The stack locals of sum (s, c, t, i, ...) are handled by the hybrid analysis:
// their accesses are not profiled, their dependencies are handed over
// statically and reported per execution of the basic blocks holding them.
int observed = 0;

void observe(int i) { observed += i; }

double sum(const double *a, int n) {
  double s = 0.0;
  double c = 0.0;
  for (int i = 0; i < n; i++) {
    double t = a[i] * 2.0;
    observe(i);
    s += t;
    if (t > 4.0) {
      c += 1.0;
    }
  }
  return s + c;
}

// may throw, so that its calls have to unwind through sum_guarded
void observe_or_throw(int i) {
  if (i < 0) {
    throw i;
  }
  observed += i;
}

struct Guard {
  ~Guard() { observed += 1; }
};

// observe_or_throw is invoked here (g has to be destroyed on unwinding), so the basic
// block holding the write of t ends with the call
double sum_guarded(const double *a, int n) {
  double s = 0.0;
  for (int i = 0; i < n; i++) {
    Guard g;
    double t = a[i];
    observe_or_throw(i);
    s += t;
  }
  return s;
}

int main() {
  double a[8];
  for (int k = 0; k < 8; k++) {
    a[k] = k;
  }
  double r = sum(a, 8) + sum_guarded(a, 8);
  return r > 0.0 ? 0 : 1;
}
