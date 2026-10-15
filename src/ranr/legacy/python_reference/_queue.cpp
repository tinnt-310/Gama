// Pure deterministic FIFO kernel. No observations, RNG, communication or policy.
// Python scalar and NumPy implementations remain independent test references.
#include <algorithm>
#include <cmath>
#include <cstddef>
extern "C" void fifo(double* free, const double* powers,
                     const double* arrivals, const double* energy,
                     const double* maximum, double* starts, double* waiting,
                     std::size_t samples, std::size_t ports,
                     std::size_t jobs, double efficiency) {
    for (std::size_t s = 0; s < samples; ++s) {
        double last = 0.0;
        double* f = free + s * ports;
        for (std::size_t j = 0; j < jobs; ++j) {
            const std::size_t k = s * jobs + j;
            if (!std::isfinite(arrivals[k])) continue;
            const double floor = std::max(arrivals[k], last);
            double begin = INFINITY;
            for (std::size_t p = 0; p < ports; ++p)
                begin = std::min(begin, std::max(f[p], floor));
            std::size_t selected = 0;
            double priority = -1.0;
            for (std::size_t p = 0; p < ports; ++p) {
                if (std::max(f[p], floor) > begin + 1e-10) continue;
                double value = std::min(powers[p], maximum[k]) - p * 1e-9;
                if (value > priority) { priority = value; selected = p; }
            }
            f[selected] = begin + 60.0 * energy[k] /
                (efficiency * std::min(powers[selected], maximum[k]));
            starts[k] = begin;
            waiting[s] += begin - arrivals[k];
            last = begin;
        }
    }
}
