// AudioEngine.cpp
#include "AudioEngine.h"

#include "VolumeController.h"

namespace ln {

AudioEngine::AudioEngine() = default;

AudioEngine::~AudioEngine()
{
    Stop();
}

bool AudioEngine::Start()
{
    if (running_.load())
        return true;
    running_.store(true);
    try
    {
        thread_ = std::thread(&AudioEngine::ThreadMain, this);
    }
    catch (...)
    {
        running_.store(false);
        return false;
    }
    return true;
}

void AudioEngine::Stop()
{
    running_.store(false);
    if (thread_.joinable())
        thread_.join();
}

void AudioEngine::ApplySettings(const Settings& settings)
{
    Settings previous;
    {
        std::lock_guard<std::mutex> lock(settingsMutex_);
        previous = settings_;
        settings_ = settings;
    }

    // 关闭自动均衡 -> 恢复所有被接管应用的原始音量
    if (previous.autoEnabled && !settings.autoEnabled)
        restoreAllRequest_.store(true);

    // 进入测试模式 -> 先还原音量，保证测试读数不被历史增益污染
    if (!previous.testMode && settings.testMode)
        restoreAllRequest_.store(true);

    // 退出测试模式 / 重新开启 -> 清除手动接管标记，重新接管
    if (previous.testMode && !settings.testMode)
        resumeManualRequest_.store(true);
    if (!previous.autoEnabled && settings.autoEnabled)
        resumeManualRequest_.store(true);
}

Settings AudioEngine::CurrentSettings() const
{
    std::lock_guard<std::mutex> lock(settingsMutex_);
    return settings_;
}

void AudioEngine::RestoreAllNow()
{
    restoreAllRequest_.store(true);
}

void AudioEngine::ResumeManualApps()
{
    resumeManualRequest_.store(true);
}

void AudioEngine::SetPaused(bool paused)
{
    paused_.store(paused);
}

std::vector<AppSnapshot> AudioEngine::Snapshots() const
{
    std::lock_guard<std::mutex> lock(snapshotMutex_);
    return snapshot_;
}

std::wstring AudioEngine::StatusText() const
{
    std::lock_guard<std::mutex> lock(snapshotMutex_);
    return status_;
}

void AudioEngine::SetStatus(const std::wstring& text)
{
    std::lock_guard<std::mutex> lock(snapshotMutex_);
    status_ = text;
}

// ---------------------------------------------------------------------------
// 工作线程
// ---------------------------------------------------------------------------
void AudioEngine::ThreadMain()
{
    const HRESULT comResult = CoInitializeEx(nullptr, COINIT_MULTITHREADED);

    deviceAvailable_ = sessionManager_.Initialize();
    if (!deviceAvailable_)
        deviceError_ = sessionManager_.LastError();

    LARGE_INTEGER frequency = {};
    LARGE_INTEGER previous = {};
    QueryPerformanceFrequency(&frequency);
    QueryPerformanceCounter(&previous);

    double refreshAccum = kSessionRefreshMs;
    double publishAccum = 0.0;

    while (running_.load())
    {
        LARGE_INTEGER now = {};
        QueryPerformanceCounter(&now);
        double dt = static_cast<double>(now.QuadPart - previous.QuadPart) /
                    static_cast<double>(frequency.QuadPart);
        previous = now;
        if (dt <= 0.0)
            dt = 0.001;
        if (dt > 0.35)
            dt = 0.35;

        const Settings settings = CurrentSettings();

        if (restoreAllRequest_.exchange(false))
            RestoreAll();

        if (resumeManualRequest_.exchange(false))
        {
            for (auto& app : apps_)
            {
                app->manualOverride = false;
                app->appliedGainDb = 0.0;
                app->inDeadZone = true;
                app->ResetControlTracking();
                if (app->baselineCaptured)
                {
                    app->baselineCaptured = false; // 下一轮以当前音量为新基准
                    app->estimator.Reset();
                }
            }
        }

        refreshAccum += dt * 1000.0;
        if (refreshAccum >= kSessionRefreshMs)
        {
            refreshAccum = 0.0;
            RefreshSessions();
        }

        Tick(settings, dt);

        publishAccum += dt * 1000.0;
        if (publishAccum >= 100.0)
        {
            publishAccum = 0.0;
            PublishSnapshot(settings);
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(static_cast<int>(kTickMs)));
    }

    // 退出：停止自动增益控制 + 恢复所有应用原始音量 + 释放会话对象
    RestoreAll();
    apps_.clear();
    sessionManager_.Shutdown();
    PublishSnapshot(CurrentSettings());
    SetStatus(L"已停止，音量已恢复");

    if (SUCCEEDED(comResult))
        CoUninitialize();
}

void AudioEngine::RefreshSessions()
{
    std::vector<RawSession> rawSessions;
    if (!sessionManager_.EnumerateSessions(rawSessions))
    {
        deviceAvailable_ = false;
        deviceError_ = sessionManager_.LastError();
        if (deviceError_.empty())
            deviceError_ = L"无法枚举音频会话";
        return;
    }

    deviceAvailable_ = true;
    deviceError_.clear();

    for (auto& app : apps_)
        app->seen = false;

    for (auto& raw : rawSessions)
    {
        const std::wstring key = raw.Key();
        if (key.empty())
            continue;

        AppSession* target = nullptr;
        for (auto& app : apps_)
        {
            if (app->key == key)
            {
                target = app.get();
                break;
            }
        }

        if (!target)
        {
            auto created = std::make_unique<AppSession>();
            created->key = key;
            created->estimator.SetWindowMs(600.0);
            apps_.push_back(std::move(created));
            target = apps_.back().get();
        }

        target->seen = true;
        target->pid = raw.pid;
        target->name = raw.BestName();
        target->control = raw.control;
        target->volume = raw.volume;
        target->meter = raw.meter;

        if (!target->baselineCaptured)
        {
            float volume = 1.0f;
            if (target->volume.Get() != nullptr)
                VolumeController::GetVolume(target->volume.Get(), volume);
            target->originalVolume = volume;
            target->lastSetVolume = volume;
            target->baselineCaptured = true;
            target->appliedGainDb = 0.0;
            target->inDeadZone = true;
            target->ResetControlTracking();
        }
    }

    // 会话消失（应用退出 / 停止音频）-> 尽力恢复原始音量后清理
    for (auto it = apps_.begin(); it != apps_.end();)
    {
        if (!(*it)->seen)
        {
            RestoreApp(**it);
            it = apps_.erase(it);
        }
        else
        {
            ++it;
        }
    }
}

void AudioEngine::RestoreApp(AppSession& app)
{
    if (!app.manualOverride && app.baselineCaptured && app.volume)
        VolumeController::Restore(app.volume.Get(), app.originalVolume);
    app.lastSetVolume = app.originalVolume;
    app.appliedGainDb = 0.0;
    app.inDeadZone = true;
    app.ResetControlTracking();
}

void AudioEngine::RestoreAll()
{
    for (auto& app : apps_)
        RestoreApp(*app);
}

void AudioEngine::Tick(const Settings& settings, double dtSeconds)
{
    for (auto& app : apps_)
        TickApp(*app, settings, dtSeconds);
}

void AudioEngine::TickApp(AppSession& app, const Settings& settings, double dtSeconds)
{
    const bool paused = paused_.load();

    // ---- 1) 读取电平与会话状态 ----
    float peak = 0.0f;
    if (app.meter)
        app.meter->GetPeakValue(&peak);

    AudioSessionState sessionState = AudioSessionStateInactive;
    if (app.control)
        app.control->GetState(&sessionState);

    app.latestPeakDbfs = LinearToDb(peak);
    const bool hasSignal = (sessionState == AudioSessionStateActive) && (app.latestPeakDbfs > kSilenceDbfs);

    app.estimator.SetWindowMs(SensitivityToWindowMs(settings.sensitivity));
    if (hasSignal)
    {
        app.estimator.AddPeakSample(peak, dtSeconds);
        app.activeMs += dtSeconds * 1000.0;
    }
    else
    {
        app.estimator.AddSilence(dtSeconds);
        app.activeMs = 0.0;
    }
    app.playing = hasSignal;
    app.estimatedLufs = app.estimator.EstimatedLufs(settings.calibrationDb);

    // ---- 2) 读取当前音量 ----
    float currentVolume = 1.0f;
    const bool hasVolume =
        (app.volume.Get() != nullptr) && VolumeController::GetVolume(app.volume.Get(), currentVolume);
    app.volumePercent = hasVolume ? currentVolume * 100.0f : 100.0f;

    const bool controlling = settings.autoEnabled && !paused && !settings.testMode && !app.manualOverride;

    // ---- 3) 检测用户手动调整音量（避免程序把用户刚改的音量立刻改回去）----
    if (controlling && hasVolume && app.baselineCaptured)
    {
        const double diff = std::fabs(static_cast<double>(currentVolume) - app.lastSetVolume);
        const double tolerance = std::max(0.01, 0.03 * static_cast<double>(app.lastSetVolume));
        if (diff > tolerance)
        {
            app.manualOverride = true;
            app.originalVolume = currentVolume; // 以用户新设置为基准
            app.lastSetVolume = currentVolume;
            app.appliedGainDb = 0.0;
            app.inDeadZone = true;
            app.ResetControlTracking();
        }
    }
    else if (!app.manualOverride && hasVolume && std::fabs(app.appliedGainDb) < 0.01 && !paused)
    {
        // 未接管状态下持续刷新基准音量
        app.originalVolume = currentVolume;
        app.lastSetVolume = currentVolume;
    }

    // ---- 4) 状态判定 ----
    if (!settings.autoEnabled)
        app.state = AppState::Disabled;
    else if (paused)
        app.state = AppState::Paused;
    else if (app.manualOverride)
        app.state = AppState::Manual;
    else if (settings.testMode)
        app.state = AppState::TestMode;
    else if (!hasSignal)
        app.state = AppState::Silent;
    else if (app.activeMs < kWarmupMs)
        app.state = AppState::Warming;

    const bool mayApply = settings.autoEnabled && !paused && !settings.testMode && !app.manualOverride &&
                          hasSignal && app.activeMs >= kWarmupMs && app.volume.Get() != nullptr;

    // ---- 5) 计算增益（测试模式/暂停/预热阶段只计算不写入）----
    const GainDecision decision = controller_.Step(app, settings, dtSeconds, mayApply);

    if (mayApply && decision.apply)
    {
        if (std::fabs(decision.appliedScalar - app.lastSetVolume) > 0.0004f)
            VolumeController::SetVolume(app.volume.Get(), decision.appliedScalar);
        app.lastSetVolume = decision.appliedScalar;
        app.appliedGainDb = VolumeController::GainOf(app.originalVolume, decision.appliedScalar);
    }
}

void AudioEngine::PublishSnapshot(const Settings& settings)
{
    std::vector<AppSnapshot> snapshots;
    snapshots.reserve(apps_.size());

    for (const auto& app : apps_)
    {
        AppSnapshot snapshot;
        snapshot.name = app->name;
        snapshot.pid = app->pid;
        snapshot.estimatedLufs = app->estimatedLufs;
        snapshot.targetLufs = settings.targetLufs;
        snapshot.appliedGainDb = app->appliedGainDb;
        snapshot.theoreticalGainDb = app->theoreticalGainDb;
        snapshot.volumePercent = app->volumePercent;
        snapshot.playing = app->playing;
        snapshot.state = app->state;
        snapshots.push_back(std::move(snapshot));
    }

    std::sort(snapshots.begin(), snapshots.end(), [](const AppSnapshot& a, const AppSnapshot& b) {
        if (a.name != b.name)
            return a.name < b.name;
        return a.pid < b.pid;
    });

    std::wstring status;
    if (!deviceAvailable_)
    {
        status = deviceError_.empty() ? L"未找到可用的音频设备，正在重试…" : deviceError_;
    }
    else if (!settings.autoEnabled)
    {
        status = L"自动均衡已关闭（应用原始音量已恢复）";
    }
    else if (settings.testMode)
    {
        status = L"测试模式：只检测与计算，不会修改任何应用音量";
    }
    else if (paused_.load())
    {
        status = L"自动均衡已暂停（保持当前音量，不再调整）";
    }
    else
    {
        int active = 0;
        for (const auto& snapshot : snapshots)
        {
            if (snapshot.state == AppState::Adjusting || snapshot.state == AppState::Stable ||
                snapshot.state == AppState::Capped)
                ++active;
        }
        status = FormatW(L"自动均衡运行中：%d 个音频会话，%d 个已接管 · 绝对目标 %.1f LUFS",
                         static_cast<int>(snapshots.size()), active, settings.targetLufs);
    }

    std::lock_guard<std::mutex> lock(snapshotMutex_);
    snapshot_ = std::move(snapshots);
    status_ = status;
}

} // namespace ln
