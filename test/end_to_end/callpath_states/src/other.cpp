struct Domain;

double helper(double x) { return x * 2.0; }

// its mangled name (_Z12setup_domainP6Domain) contains "main"
void setup_domain(Domain* d) {}

struct Table {
  double cells[8];
  Table(int n);
};

// called from main.cpp only
Table::Table(int n) {
  for (int i = 0; i < 8; ++i) {
    cells[i] = i + n;
  }
}
