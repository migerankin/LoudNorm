// Common.h - 公共定义 / 工具函数
// Absolute Loudness Normalizer (LoudNorm) MVP
#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef WINVER
#define WINVER 0x0A00
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>
#include <shellapi.h>
#include <commctrl.h>
#include <wrl/client.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdarg>
#include <cstdlib>
#include <cwchar>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "version.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "shell32.lib")

namespace ln {

using Microsoft::WRL::ComPtr;

// ---- 窗口 / 消息约定 -------------------------------------------------------
constexpr wchar_t kMainWindowClass[] = L"LoudNormMainWindowClass";
constexpr wchar_t kAppTitle[] = L"LoudNorm - 绝对响度自动均衡 (MVP)";
constexpr UINT kTrayCallbackMessage = WM_APP + 1;  // 托盘图标回调
constexpr UINT kShowWindowMessage = WM_APP + 2;    // 第二个实例请求显示主窗口

// ---- 通用常量 --------------------------------------------------------------
// 判定“无音频播放”的电平门限（dBFS）。低于该值不参与响度统计，也不做增益调整。
constexpr double kSilenceDbfs = -62.0;

// 新应用开始播放后的预热时间，避免“刚开始出声就被大幅放大”。
constexpr double kWarmupMs = 900.0;

// 会话重新枚举周期（毫秒）。
constexpr double kSessionRefreshMs = 1000.0;

// 引擎采样周期（毫秒）。
constexpr double kTickMs = 25.0;

// ---- 数学工具 --------------------------------------------------------------
inline double Clamp(double v, double lo, double hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

inline double LinearToDb(double amplitude)
{
    return amplitude > 1e-7 ? 20.0 * std::log10(amplitude) : -140.0;
}

inline double DbToLinear(double db)
{
    return std::pow(10.0, db / 20.0);
}

// 灵敏度 0..100 -> 响度统计窗口 2500ms..250ms（值越大响应越快）
inline double SensitivityToWindowMs(double sensitivity)
{
    const double s = Clamp(sensitivity, 0.0, 100.0) / 100.0;
    return 2500.0 - s * 2250.0;
}

// 调整速度 0..100 -> 每秒允许的最大增益变化 0.5..10 dB/s
inline double SpeedToRateDbPerSec(double speed)
{
    const double s = Clamp(speed, 0.0, 100.0) / 100.0;
    return 0.5 + s * 9.5;
}

inline double RateDbPerSecToSpeed(double rate)
{
    return Clamp((rate - 0.5) / 9.5 * 100.0, 0.0, 100.0);
}

inline std::wstring FormatW(const wchar_t* fmt, ...)
{
    wchar_t buffer[512] = {};
    va_list args;
    va_start(args, fmt);
    _vsnwprintf_s(buffer, 512, _TRUNCATE, fmt, args);
    va_end(args);
    return std::wstring(buffer);
}

// 例如：-14.2 / +7.7
inline std::wstring FormatDb(double db)
{
    if (db <= -139.0)
        return L"--";
    return FormatW(L"%+.1f", db);
}

inline std::wstring FormatLufs(double db)
{
    if (db <= -139.0)
        return L"--";
    return FormatW(L"%.1f", db);
}

} // namespace ln
