// LoudnessEstimator.h - 基于 WASAPI Peak Meter 的“估算响度”计算
//
// 说明（重要）：
//   WASAPI 的音频会话只提供 IAudioMeterInformation 的峰值电平（线性 0..1），
//   不提供 PCM 数据，因此无法做 ITU-R BS.1770 的 K 加权 + 门限统计，
//   所以这里得到的是 Estimated Loudness（估算响度），不是专业 LUFS-I。
//   为实现“听感接近绝对目标”的闭环，这里对采样峰值做滑动均方统计，
//   再叠加一个可调校准量（默认 -12 dB，用于补偿“峰值包络 vs 真实 RMS”的差异）。
#pragma once

#include "Common.h"

namespace ln {

class LoudnessEstimator
{
public:
    void SetWindowMs(double windowMs) { windowMs_ = std::max(80.0, windowMs); }
    double WindowMs() const { return windowMs_; }

    // 传入一次峰值采样（线性 0..1）与本次采样间隔（秒）
    void AddPeakSample(float linearPeak, double dtSeconds);
    // 无音频时调用：只推进静音计时，不污染响度统计
    void AddSilence(double dtSeconds);
    void Reset();

    // 估算响度（估算 LUFS）：10*log10(meanSquare) + calibrationDb
    double EstimatedLufs(double calibrationDb) const;
    double LatestPeakDbfs() const { return LinearToDb(latestPeak_); }
    bool IsSilent() const { return silentMs_ >= 250.0; }
    double SilentMs() const { return silentMs_; }
    double MeanSquare() const { return meanSquare_; }

private:
    double windowMs_ = 600.0;
    double meanSquare_ = 0.0;
    double latestPeak_ = 0.0;
    double silentMs_ = 1000.0;
};

} // namespace ln
