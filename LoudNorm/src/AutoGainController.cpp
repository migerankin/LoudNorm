// AutoGainController.cpp
#include "AutoGainController.h"

#include "VolumeController.h"

namespace ln {

GainDecision AutoGainController::Step(AppSession& app, const Settings& s, double dtSeconds, bool mayApply)
{
    GainDecision decision;

    // 本征响度：假设“测量值 = 本征响度 + slope * 已施加增益”
    //   slope = 0：峰值表与会话音量无关 -> 前馈直接计算 targetGain = target - estimated
    //   slope = 1：峰值表随会话音量变化   -> 闭环反馈（边调边测）
    // 默认前馈（与开发文档的 targetGain 公式一致）；运行中由回归自动识别，
    // 详见 AutoGainController::UpdateResponseSlope。
    const auto intrinsic = [&app]() {
        return app.estimatedLufs - app.responseSlope * app.appliedGainDb;
    };

    if (!mayApply)
    {
        app.theoreticalGainDb = Clamp(s.targetLufs - intrinsic(), s.minGainDb, s.maxGainDb);
        return decision;
    }

    if (app.originalVolume < 0.02f)
    {
        // 原始音量几乎为 0，没有可用余量
        app.theoreticalGainDb = Clamp(s.targetLufs - app.estimatedLufs, s.minGainDb, s.maxGainDb);
        app.state = AppState::Capped;
        return decision;
    }

    RecordSample(app, dtSeconds);

    const double desired = Clamp(s.targetLufs - intrinsic(), s.minGainDb, s.maxGainDb);
    const double error = desired - app.appliedGainDb;
    app.theoreticalGainDb = desired;

    // ---- 死区（迟滞）：误差足够小就不动，避免音量抖动 ----
    const double enterZone = std::max(0.15, s.deadZoneDb);
    const double exitZone = std::max(0.05, s.deadZoneDb * 0.4);
    if (app.inDeadZone)
    {
        if (std::fabs(error) < enterZone)
        {
            app.state = AppState::Stable;
            return decision;
        }
        app.inDeadZone = false;
    }
    else if (std::fabs(error) <= exitZone)
    {
        app.inDeadZone = true;
        app.state = AppState::Stable;
        return decision;
    }

    // ---- Attack / Release 指数平滑 + 每秒变化量限制 ----
    const double tauMs = (error > 0.0 ? std::max(50.0, s.attackMs) : std::max(50.0, s.releaseMs));
    const double dtMs = std::max(1.0, dtSeconds * 1000.0);
    double step = error * (1.0 - std::exp(-dtMs / tauMs));
    const double maxStep = std::max(0.05, s.rateDbPerSec) * dtSeconds;
    step = Clamp(step, -maxStep, maxStep);

    const double newGain = Clamp(app.appliedGainDb + step, s.minGainDb, s.maxGainDb);

    decision.apply = true;
    decision.requestedGainDb = newGain;
    decision.appliedScalar = VolumeController::ScalarForGain(app.originalVolume, newGain);

    const double achieved = VolumeController::GainOf(app.originalVolume, decision.appliedScalar);
    decision.capped = (newGain - achieved) > 0.1;

    app.capped = decision.capped;
    app.theoreticalGainDb = newGain;
    app.state = decision.capped ? AppState::Capped : AppState::Adjusting;
    return decision;
}

void AutoGainController::RecordSample(AppSession& app, double dtSeconds)
{
    const double dtMs = std::max(1.0, dtSeconds * 1000.0);
    const double gainDelta = std::fabs(app.appliedGainDb - app.lastSampleGain);
    app.lastSampleGain = app.appliedGainDb;
    app.stableGainMs = (gainDelta < 0.03) ? app.stableGainMs + dtMs : 0.0;

    // 每 450ms 记录一组 (施加增益, 实测响度)，用于回归分析
    app.sampleTimerMs += dtMs;
    if (app.sampleTimerMs < 450.0)
        return;
    app.sampleTimerMs = 0.0;

    SlopeSample sample;
    sample.gainDb = app.appliedGainDb;
    sample.loudness = app.estimatedLufs;
    app.slopeSamples.push_back(sample);
    while (app.slopeSamples.size() > 24)
        app.slopeSamples.pop_front();

    UpdateResponseSlope(app);
}

// 用线性回归估计“测量响度 / 施加增益”的斜率：
// 斜率 ≈ 1 -> 峰值表随会话音量变化（闭环）；斜率 ≈ 0 -> 不随音量变化（前馈）。
void AutoGainController::UpdateResponseSlope(AppSession& app)
{
    const size_t count = app.slopeSamples.size();
    if (count < 10)
        return;

    double minGain = 1e9;
    double maxGain = -1e9;
    double meanGain = 0.0;
    double meanLoudness = 0.0;
    for (const auto& sample : app.slopeSamples)
    {
        minGain = std::min(minGain, sample.gainDb);
        maxGain = std::max(maxGain, sample.gainDb);
        meanGain += sample.gainDb;
        meanLoudness += sample.loudness;
    }
    meanGain /= static_cast<double>(count);
    meanLoudness /= static_cast<double>(count);

    // 增益变化幅度不足，无法判断响应关系
    if (maxGain - minGain < 2.0)
        return;

    double variance = 0.0;
    double varianceLoudness = 0.0;
    double covariance = 0.0;
    for (const auto& sample : app.slopeSamples)
    {
        const double dg = sample.gainDb - meanGain;
        const double dm = sample.loudness - meanLoudness;
        variance += dg * dg;
        varianceLoudness += dm * dm;
        covariance += dg * dm;
    }
    if (variance < 1e-6 || varianceLoudness < 1e-6)
        return;

    // 相关系数足够高才认为“响度确实跟着增益变化”，避免音乐本身强弱起伏造成误判
    const double denominator = std::sqrt(variance * varianceLoudness);
    if (denominator < 1e-9)
        return;
    const double correlation = covariance / denominator;
    if (std::fabs(correlation) < 0.7)
        return;

    const double slope = Clamp(covariance / variance, -0.25, 1.5);
    app.responseSlope = Clamp(app.responseSlope + 0.3 * (slope - app.responseSlope), 0.0, 1.0);
}

} // namespace ln
