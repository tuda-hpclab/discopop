#ifndef UTIL_HPP
#define UTIL_HPP

#include <string>
#include <vector>

namespace app {

struct Particle {
  double position;
  double velocity;
  double Energy() const { return 0.5 * velocity * velocity; }
};

template <typename T>
T Sum(const std::vector<T>& values) {
  T total = T();
  for (const T& value : values) {
    total += value;
  }
  return total;
}

}  // namespace app

#endif
