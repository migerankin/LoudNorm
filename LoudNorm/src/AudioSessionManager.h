// AudioSessionManager.h - 发现 / 监听 / 管理 Windows 音频会话（WASAPI）
#pragma once

#include "Common.h"

#include <audiopolicy.h>
#include <endpointvolume.h>
#include <mmdeviceapi.h>

namespace ln {

// 一次枚举得到的“原始会话”信息（持有 COM 接口，仅在工作线程内使用）
struct RawSession
{
    ComPtr<IAudioSessionControl2> control;
    ComPtr<ISimpleAudioVolume> volume;
    ComPtr<IAudioMeterInformation> meter;
    DWORD pid = 0;
    AudioSessionState state = AudioSessionStateInactive;
    std::wstring instanceId;   // 会话实例唯一标识
    std::wstring displayName;  // 应用自己注册的显示名（可能为空）
    std::wstring processName;  // 进程文件名
    std::wstring friendlyName; // 文件描述（中文名优先）

    std::wstring Key() const;
    std::wstring BestName() const;
};

class AudioSessionManager
{
public:
    AudioSessionManager();
    ~AudioSessionManager();

    AudioSessionManager(const AudioSessionManager&) = delete;
    AudioSessionManager& operator=(const AudioSessionManager&) = delete;

    // 必须在已 CoInitializeEx 的线程调用
    bool Initialize();
    void Shutdown();
    bool IsReady() const { return sessionManager_ != nullptr; }

    // 枚举默认渲染设备上的所有音频会话
    bool EnumerateSessions(std::vector<RawSession>& out);

    // 最近一次失败原因
    const std::wstring& LastError() const { return lastError_; }

private:
    bool OpenDevice();

    ComPtr<IMMDeviceEnumerator> enumerator_;
    ComPtr<IMMDevice> device_;
    ComPtr<IAudioSessionManager2> sessionManager_;
    ComPtr<IMMNotificationClient> notification_;
    std::atomic<bool> deviceDirty_{false};
    std::wstring lastError_;

    // 进程名 / 文件描述缓存（仅工作线程访问）
    struct ProcessNameCache;
    std::unique_ptr<ProcessNameCache> processNames_;
};

} // namespace ln
