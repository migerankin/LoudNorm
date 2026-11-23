// AudioEngine.h - 后台音频引擎：发现会话 / 采样电平 / 估算响度 / 计算并施加增益
//
// 线程模型：
//   主线程（UI，STA COM）  —— 只读取快照、写入设置，不接触任何音频接口
//   工作线程（MTA COM）    —— 独占 IMMDeviceEnumerator / IAudioSessionManager2 /
//                             ISimpleAudioVolume / IAudioMeterInformation
#pragma once

#include "AppSession.h"
#include "AudioSessionManager.h"
#include "AutoGainController.h"
#include "Common.h"
#include "Settings.h"

#include <thread>

namespace ln {

struct AppSnapshot
{
    std::wstring name;
    DWORD pid = 0;
    double estimatedLufs = -140.0;
    double targetLufs = -16.0;
    double appliedGainDb = 0.0;
    double theoreticalGainDb = 0.0;
    double volumePercent = 100.0;
    bool playing = false;
    AppState state = AppState::Disabled;
};

class AudioEngine
{
public:
    AudioEngine();
    ~AudioEngine();

    AudioEngine(const AudioEngine&) = delete;
    AudioEngine& operator=(const AudioEngine&) = delete;

    bool Start();
    void Stop();
    bool IsRunning() const { return running_.load(); }

    // ---- UI 线程调用 ----
    void ApplySettings(const Settings& settings);
    Settings CurrentSettings() const;
    void RestoreAllNow();
    void ResumeManualApps();
    void SetPaused(bool paused);
    bool IsPaused() const { return paused_.load(); }

    std::vector<AppSnapshot> Snapshots() const;
    std::wstring StatusText() const;

private:
    void ThreadMain();
    void Tick(const Settings& settings, double dtSeconds);
    void TickApp(AppSession& app, const Settings& settings, double dtSeconds);
    void RefreshSessions();
    void RestoreApp(AppSession& app);
    void RestoreAll();
    void PublishSnapshot(const Settings& settings);
    void SetStatus(const std::wstring& text);

    // 线程与状态
    std::thread thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> paused_{false};
    std::atomic<bool> restoreAllRequest_{false};
    std::atomic<bool> resumeManualRequest_{false};

    // 设置（UI 写 -> 引擎读）
    mutable std::mutex settingsMutex_;
    Settings settings_;

    // 快照（引擎写 -> UI 读）
    mutable std::mutex snapshotMutex_;
    std::vector<AppSnapshot> snapshot_;
    std::wstring status_;

    // 仅工作线程访问
    AudioSessionManager sessionManager_;
    AutoGainController controller_;
    std::vector<std::unique_ptr<AppSession>> apps_;
    bool deviceAvailable_ = false;
    std::wstring deviceError_;
};

} // namespace ln
