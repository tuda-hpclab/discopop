#include <cstdlib>
#include <vector>

struct Domain;
double helper(double x);
void setup_domain(Domain* d);

// a loop in a function reached only after
// - a call to a function defined in a system header (std::vector), which is not instrumented
// - a call to a function of another translation unit
double work(double* a, int n) {
  double s = 0;
  for (int i = 0; i < n; ++i) {
    a[i] = i;
    s += a[i];
  }
  return s;
}

double driver(double* a, int n) {
  std::vector<double> v(n, 1.0);
  double s = v[0];
  s += helper(1.0);
  s += work(a, n);
  return s;
}

// a constructor defined outside of its class: clang emits the complete-object constructor (C1),
// which `new Buffer(...)` and `Buffer b(...)` call, as an alias of the base-object constructor (C2)
struct Buffer {
  double data[8];
  Buffer(int n);
};

Buffer::Buffer(int n) {
  for (int i = 0; i < 8; ++i) {
    data[i] = i * n;
  }
}

// a constructor defined in another translation unit
struct Table {
  double cells[8];
  Table(int n);
};

// a loop in a function reached only after an indirect call of a function without instrumentation
double after_indirect_call(double* a, int n) {
  double s = 0;
  for (int i = 0; i < n; ++i) {
    s += a[i];
  }
  return s;
}

// a virtual method, only called through a pointer to the base class
struct Shape {
  virtual double area(double* a, int n) = 0;
  virtual ~Shape() {}
};
struct Square : Shape {
  double area(double* a, int n) override {
    double s = 0;
    for (int i = 0; i < n; ++i) {
      s += a[i];
    }
    return s;
  }
};

// an exception thrown through a function with a destructor cleanup, caught in main
struct Guard {
  double* target;
  ~Guard() { target[0] += 1; }
};

void may_throw(double* a, int i) {
  Guard guard{a};
  if (i == 3) {
    throw i;
  }
  a[i] += i;
}

// a loop in a function called after the exception was caught
double after_exception(double* a, int n) {
  double s = 0;
  for (int i = 0; i < n; ++i) {
    s += a[i];
  }
  return s;
}

// a bottom-tested loop: its header is its body, it has no loop increment instrumentation
double bottom_tested(double* a, int n) {
  int i = 0;
  do {
    a[i] += 1;
    ++i;
  } while (i < n);
  return a[0];
}

int main(int argc, char** argv) {
  int n = 20;
  double* a = new double[n];
  setup_domain(nullptr);
  double s = driver(a, n);

  Buffer* heap_buffer = new Buffer(2);
  Buffer stack_buffer(3);
  Table* heap_table = new Table(4);
  Table stack_table(5);
  s += heap_buffer->data[1] + stack_buffer.data[2] + heap_table->cells[3] + stack_table.cells[4];

  int (*absolute)(int) = &std::abs;
  if (argc > 100) {
    absolute = nullptr;
  }
  s += absolute(-3);
  s += after_indirect_call(a, n);

  for (int i = 0; i < 5; ++i) {
    try {
      may_throw(a, i);
    } catch (int e) {
      a[1] += e;
    }
  }
  s += after_exception(a, n);
  s += bottom_tested(a, n);

  Shape* shape = new Square();
  s += shape->area(a, n);

  delete shape;
  delete heap_table;
  delete heap_buffer;
  delete[] a;
  return s > 0 ? 0 : 1;
}
