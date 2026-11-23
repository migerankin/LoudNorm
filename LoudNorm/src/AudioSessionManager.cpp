// AudioSessionManager.cpp
#include "AudioSessionManager.h"

#include <unordered_map>
#include <winver.h>

namespace ln {

// ---------------------------------------------------------------------------
// 进程名 / 文件描述查询（带缓存）
// ---------------------------------------------------------------------------
struct AudioSessionManager::ProcessNameCache
{
    struct Entry
    {
        std::wstring processName;
        std::wstring friendlyName;
    };
    std::unordered_map<DWORD, Entry> byPid;
    std::unordered_map<std::wstring, std::wstring> descriptions;
};

namespace {

std::wstring QueryProcessPath(DWORD pid)
{
    std::wstring path;
    if (pid == 0)
        return path;
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!process)
        return path;
    wchar_t buffer[2048] = {};
    DWORD size = 2048;
    if (QueryFullProcessImageNameW(process, 0, buffer, &size))
        path.assign(buffer, size);
    CloseHandle(process);
    return path;
}

std::wstring FileNameOf(const std::wstring& path)
{
    const size_t pos = path.find_last_of(L"\\/");
    std::wstring name = (pos == std::wstring::npos) ? path : path.substr(pos + 1);
    const size_t dot = name.find_last_of(L'.');
    if (dot != std::wstring::npos && dot > 0)
        name = name.substr(0, dot);
    return name;
}

std::wstring QueryFileDescription(const std::wstring& path)
{
    DWORD handle = 0;
    const DWORD size = GetFileVersionInfoSizeW(path.c_str(), &handle);
    if (size == 0)
        return std::wstring();

    std::vector<BYTE> data(size);
    if (!GetFileVersionInfoW(path.c_str(), 0, size, data.data()))
        return std::wstring();

    struct Translation
    {
        WORD language;
        WORD codePage;
    };
    Translation* translations = nullptr;
    UINT translationSize = 0;
    if (!VerQueryValueW(data.data(), L"\\VarFileInfo\\Translation",
                        reinterpret_cast<LPVOID*>(&translations), &translationSize) ||
        translationSize < sizeof(Translation) || translations == nullptr)
    {
        return std::wstring();
    }

    wchar_t subBlock[128];
    swprintf_s(subBlock, L"\\StringFileInfo\\%04x%04x\\FileDescription",
               translations[0].language, translations[0].codePage);

    wchar_t* description = nullptr;
    UINT descriptionSize = 0;
    if (VerQueryValueW(data.data(), subBlock, reinterpret_cast<LPVOID*>(&description), &descriptionSize) &&
        descriptionSize > 1 && description != nullptr)
    {
        return std::wstring(description);
    }
    return std::wstring();
}

} // namespace

std::wstring RawSession::Key() const
{
    if (!instanceId.empty())
        return instanceId;
    return FormatW(L"pid:%lu", pid);
}

std::wstring RawSession::BestName() const
{
    if (!friendlyName.empty())
        return friendlyName;
    if (!displayName.empty())
        return displayName;
    if (!processName.empty())
        return processName;
    if (pid == 0)
        return L"系统声音";
    return FormatW(L"进程 %lu", pid);
}

// ---------------------------------------------------------------------------
// 设备变更通知（默认播放设备切换时重建会话管理器）
// ---------------------------------------------------------------------------
class DeviceNotificationClient : public IMMNotificationClient
{
public:
    explicit DeviceNotificationClient(std::atomic<bool>* dirty) : dirty_(dirty) {}

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppvObject) override
    {
        if (ppvObject == nullptr)
            return E_POINTER;
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IMMNotificationClient))
        {
            *ppvObject = static_cast<IMMNotificationClient*>(this);
            AddRef();
            return S_OK;
        }
        *ppvObject = nullptr;
        return E_NOINTERFACE;
    }

    ULONG STDMETHODCALLTYPE AddRef() override
    {
        return ++references_;
    }

    ULONG STDMETHODCALLTYPE Release() override
    {
        const ULONG value = --references_;
        if (value == 0)
            delete this;
        return value;
    }

    HRESULT STDMETHODCALLTYPE OnDefaultDeviceChanged(EDataFlow flow, ERole role, LPCWSTR) override
    {
        if (flow == eRender && (role == eConsole || role == eMultimedia))
        {
            if (dirty_)
                dirty_->store(true);
        }
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE OnDeviceAdded(LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE OnDeviceRemoved(LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE OnDeviceStateChanged(LPCWSTR, DWORD) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE OnPropertyValueChanged(LPCWSTR, const PROPERTYKEY) override { return S_OK; }

private:
    ~DeviceNotificationClient() = default;

    std::atomic<ULONG> references_{1};
    std::atomic<bool>* dirty_ = nullptr;
};

// ---------------------------------------------------------------------------
// AudioSessionManager
// ---------------------------------------------------------------------------
AudioSessionManager::AudioSessionManager()
    : processNames_(std::make_unique<ProcessNameCache>())
{
}

AudioSessionManager::~AudioSessionManager()
{
    Shutdown();
}

bool AudioSessionManager::Initialize()
{
    Shutdown();

    ComPtr<IMMDeviceEnumerator> enumerator;
    HRESULT hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                                  IID_PPV_ARGS(&enumerator));
    if (FAILED(hr) || !enumerator)
    {
        lastError_ = FormatW(L"CoCreateInstance(MMDeviceEnumerator) 失败: 0x%08X", hr);
        return false;
    }
    enumerator_ = enumerator;

    deviceDirty_.store(false);
    notification_.Attach(new DeviceNotificationClient(&deviceDirty_));
    enumerator_->RegisterEndpointNotificationCallback(notification_.Get());

    if (!OpenDevice())
    {
        lastError_ = L"未找到可用的默认播放设备（将自动重试）";
        return true; // 枚举器已就绪，等待设备出现
    }
    return true;
}

void AudioSessionManager::Shutdown()
{
    if (enumerator_ && notification_)
        enumerator_->UnregisterEndpointNotificationCallback(notification_.Get());
    notification_.Reset();
    sessionManager_.Reset();
    device_.Reset();
    enumerator_.Reset();
    deviceDirty_.store(false);
    if (processNames_)
    {
        processNames_->byPid.clear();
        processNames_->descriptions.clear();
    }
}

bool AudioSessionManager::OpenDevice()
{
    sessionManager_.Reset();
    device_.Reset();
    if (!enumerator_)
        return false;

    ComPtr<IMMDevice> device;
    HRESULT hr = enumerator_->GetDefaultAudioEndpoint(eRender, eConsole, &device);
    if (FAILED(hr) || !device)
        return false;

    ComPtr<IAudioSessionManager2> manager;
    hr = device->Activate(__uuidof(IAudioSessionManager2), CLSCTX_ALL, nullptr, &manager);
    if (FAILED(hr) || !manager)
    {
        lastError_ = FormatW(L"Activate(IAudioSessionManager2) 失败: 0x%08X", hr);
        return false;
    }

    device_ = device;
    sessionManager_ = manager;
    return true;
}

bool AudioSessionManager::EnumerateSessions(std::vector<RawSession>& out)
{
    out.clear();
    if (!enumerator_)
        return false;

    if (deviceDirty_.exchange(false))
        OpenDevice();

    if (!sessionManager_ && !OpenDevice())
        return false;

    ComPtr<IAudioSessionEnumerator> sessionEnumerator;
    HRESULT hr = sessionManager_->GetSessionEnumerator(&sessionEnumerator);
    if (FAILED(hr) || !sessionEnumerator)
    {
        lastError_ = FormatW(L"GetSessionEnumerator 失败: 0x%08X", hr);
        return false;
    }

    int count = 0;
    if (FAILED(sessionEnumerator->GetCount(&count)))
        return false;

    const DWORD selfPid = GetCurrentProcessId();

    for (int i = 0; i < count; ++i)
    {
        ComPtr<IAudioSessionControl> controlBase;
        if (FAILED(sessionEnumerator->GetSession(i, &controlBase)) || !controlBase)
            continue;

        RawSession raw;
        if (FAILED(controlBase.As(&raw.control)) || !raw.control)
            continue;

        controlBase.As(&raw.volume);
        controlBase.As(&raw.meter);

        raw.control->GetProcessId(&raw.pid);
        if (raw.pid == selfPid)
            continue; // 不处理自身

        raw.control->GetState(&raw.state);

        LPWSTR text = nullptr;
        if (SUCCEEDED(raw.control->GetSessionInstanceIdentifier(&text)) && text)
        {
            raw.instanceId = text;
            CoTaskMemFree(text);
            text = nullptr;
        }
        if (SUCCEEDED(controlBase->GetDisplayName(&text)) && text)
        {
            raw.displayName = text;
            CoTaskMemFree(text);
            text = nullptr;
        }

        // 进程名 / 文件描述（带缓存）
        auto cached = processNames_->byPid.find(raw.pid);
        if (cached != processNames_->byPid.end())
        {
            raw.processName = cached->second.processName;
            raw.friendlyName = cached->second.friendlyName;
        }
        else if (raw.pid != 0)
        {
            ProcessNameCache::Entry entry;
            const std::wstring path = QueryProcessPath(raw.pid);
            if (!path.empty())
            {
                entry.processName = FileNameOf(path);
                auto desc = processNames_->descriptions.find(path);
                if (desc != processNames_->descriptions.end())
                {
                    entry.friendlyName = desc->second;
                }
                else
                {
                    entry.friendlyName = QueryFileDescription(path);
                    processNames_->descriptions[path] = entry.friendlyName;
                }
            }
            else
            {
                entry.processName = FormatW(L"进程 %lu", raw.pid);
            }
            raw.processName = entry.processName;
            raw.friendlyName = entry.friendlyName;
            processNames_->byPid[raw.pid] = entry;
        }
        else
        {
            raw.friendlyName = L"系统声音";
        }

        out.push_back(std::move(raw));
    }

    return true;
}

} // namespace ln
