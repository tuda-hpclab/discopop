#include <cstdio>
#include <string>
#include <vector>

#include "util.hpp"

namespace {
int global_counter = 0;
}

int main(int argc, char** argv) {
  std::vector<app::Particle> particles(32);
  std::vector<double> energies;
  for (int i = 0; i < 32; ++i) {
    particles[i].position = i;
    particles[i].velocity = 0.5 * i + argc;
    energies.push_back(particles[i].Energy());
    global_counter += i;
  }
  std::string label = "energy";
  auto scaled = [&](double factor) { return app::Sum(energies) * factor; };
  std::printf("%s %f %d\n", label.c_str(), scaled(2.0), global_counter);
  return argv == nullptr;
}
