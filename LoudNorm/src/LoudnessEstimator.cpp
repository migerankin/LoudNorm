// LoudnessEstimator.cpp
#include "LoudnessEstimator.h"

namespace ln {

void LoudnessEstimator::AddPeakSample(float linearPeak, double dtSeconds)
{
    const double peak = Clamp(static_cast<double>(linearPeak), 0.0, 1.0);
    latestPeak_ = peak;
    silentMs_ = 0.0;

    const double dtMs = std::max(1.0, dtSeconds * 1000.0);
    // 指数滑动平均：时间常数 = windowMs_
    const double alpha = 1.0 - std::exp(-dtMs / windowMs_);
    const double meanSquareSample = peak * peak;
    meanSquare_ += alpha * (meanSquareSample - meanSquare_);
    if (meanSquare_ < 1e-12)
        meanSquare_ = 0.0;
}

void LoudnessEstimator::AddSilence(double dtSeconds)
{
    latestPeak_ = 0.0;
    silentMs_ += std::max(0.0, dtSeconds * 1000.0);

    // 静音时慢速衰减，避免“声音一停响度归零”导致恢复播放时瞬间大幅增益
    const double dtMs = std::max(1.0, dtSeconds * 1000.0);
    const double alpha = 1.0 - std::exp(-dtMs / (windowMs_ * 4.0));
    meanSquare_ += alpha * (0.0 - meanSquare_);
    if (meanSquare_ < 1e-12)
        meanSquare_ = 0.0;
}

void LoudnessEstimator::Reset()
{
    meanSquare_ = 0.0;
    latestPeak_ = 0.0;
    silentMs_ = 1000.0;
}

double LoudnessEstimator::EstimatedLufs(double calibrationDb) const
{
    if (meanSquare_ <= 1e-12)
        return -140.0;
    return 10.0 * std::log10(meanSquare_) + calibrationDb;
}

} // namespace ln
