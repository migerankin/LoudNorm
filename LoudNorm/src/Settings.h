// Settings.h - 用户可配置参数（全局唯一基准：绝对目标响度）
#pragma once

#include "Common.h"

namespace ln {

// 目标响度允许范围（绝对值基准，越界输入会被钳制到该区间）
constexpr double kTargetLufsMin = -60.0;
constexpr double kTargetLufsMax = 0.0;

struct Settings
{
    // 绝对目标响度（LUFS 近似值）。所有应用都以它为唯一基准，互不作为参考源。
    double targetLufs = -16.0;

    bool autoEnabled = true;   // 自动均衡总开关
    bool testMode = false;     // 测试模式：只计算，绝不改变音量

    double maxGainDb = 12.0;   // 最大自动增益
    double minGainDb = -12.0;  // 最大自动衰减

    double attackMs = 800.0;   // 低于目标（需要提升）时的响应时间
    double releaseMs = 350.0;  // 高于目标（需要衰减）时的响应时间

    // 每秒允许的最大增益变化量（dB/s），限制变化速度，避免 pumping
    double rateDbPerSec = 3.0;

    // 灵敏度（0..100）：控制响度统计窗口长度（越大越快，但越容易抖动）
    double sensitivity = 75.0;

    // 响度估算校准（dB）：补偿“峰值包络均方”与真实 RMS/LUFS 的系统差
    double calibrationDb = -12.0;

    // 死区（dB）：误差小于该值时不调整，避免音量抖动
    double deadZoneDb = 1.0;

    bool startMinimized = false;
    bool minimizeToTrayOnClose = true;
};

// 目标响度预设（UI 下拉框）
struct LoudnessPreset
{
    double value;
    const wchar_t* label;
};

inline const LoudnessPreset* LoudnessPresets(int& count)
{
    static const LoudnessPreset kPresets[] = {
        { -27.0, L"-27 LUFS (电视广播)" },
        { -23.0, L"-23 LUFS (EBU R128)" },
        { -20.0, L"-20 LUFS" },
        { -19.0, L"-19 LUFS" },
        { -18.0, L"-18 LUFS" },
        { -16.0, L"-16 LUFS (推荐)" },
        { -15.0, L"-15 LUFS" },
        { -14.0, L"-14 LUFS (流媒体)" },
        { -12.0, L"-12 LUFS" },
        { -10.0, L"-10 LUFS (高响度)" },
    };
    count = static_cast<int>(sizeof(kPresets) / sizeof(kPresets[0]));
    return kPresets;
}

} // namespace ln
