// AppSession.h - 单个应用的完整状态（原始音量 / 当前增益 / 接管状态 / 测量数据）
#pragma once

#include "Common.h"
#include "LoudnessEstimator.h"

#include <audiopolicy.h>
#include <endpointvolume.h>

namespace ln {

enum class AppState
{
    Silent = 0,   // 未播放
    Warming,      // 预热中（刚出声，先观察）
    Adjusting,    // 正在调整
    Stable,       // 稳定（死区内）
    Capped,       // 已达增益上限 / 无可用余量
    Manual,       // 用户手动接管
    Paused,       // 已暂停
    TestMode,     // 测试模式（只计算不调整）
    Disabled,     // 自动均衡已关闭
};

inline const wchar_t* AppStateText(AppState state)
{
    switch (state)
    {
    case AppState::Silent: return L"未播放";
    case AppState::Warming: return L"预热中";
    case AppState::Adjusting: return L"正在调整";
    case AppState::Stable: return L"稳定";
    case AppState::Capped: return L"已达上限";
    case AppState::Manual: return L"手动接管";
    case AppState::Paused: return L"已暂停";
    case AppState::TestMode: return L"测试模式";
    case AppState::Disabled: return L"已关闭";
    }
    return L"--";
}

struct SlopeSample
{
    double gainDb = 0.0;
    double loudness = 0.0;
};

class AppSession
{
public:
    // ---- 标识 ----
    std::wstring key;
    std::wstring name;
    DWORD pid = 0;

    // ---- COM 接口（工作线程持有，每次重新枚举后刷新）----
    ComPtr<IAudioSessionControl2> control;
    ComPtr<ISimpleAudioVolume> volume;
    ComPtr<IAudioMeterInformation> meter;
    bool seen = false;

    // ---- 测量 ----
    LoudnessEstimator estimator;
    double estimatedLufs = -140.0;
    double latestPeakDbfs = -140.0;
    bool playing = false;
    double activeMs = 0.0; // 连续有声时长

    // ---- 控制 ----
    double appliedGainDb = 0.0;     // 当前实际施加的增益（相对原始音量）
    double theoreticalGainDb = 0.0; // 理论所需增益（测试模式也会显示）
    // 电平对会话音量的响应斜率：0=峰值表不受会话音量影响（前馈），1=随音量变化（闭环）
    // 默认 0，运行时由 AutoGainController 的回归统计自动识别。
    double responseSlope = 0.0;
    float originalVolume = 1.0f;    // 接管前的原始音量
    float lastSetVolume = 1.0f;     // 本程序最后一次写入的音量
    bool baselineCaptured = false;
    bool manualOverride = false;
    bool inDeadZone = true;
    bool capped = false;
    float volumePercent = 100.0f;

    AppState state = AppState::Disabled;

    // ---- 响应斜率估计 ----
    std::deque<SlopeSample> slopeSamples;
    double stableGainMs = 0.0;
    double sampleTimerMs = 0.0;
    double lastSampleGain = 0.0;

    void ResetControlTracking()
    {
        slopeSamples.clear();
        stableGainMs = 0.0;
        sampleTimerMs = 0.0;
        lastSampleGain = appliedGainDb;
    }
};

} // namespace ln
