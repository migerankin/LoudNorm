// SettingsManager.cpp
#include "SettingsManager.h"

#include <shlobj.h>

#include <cstdlib>

namespace ln {

namespace {

std::wstring AppDataDir()
{
    PWSTR path = nullptr;
    std::wstring result;
    if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_RoamingAppData, 0, nullptr, &path)) && path)
    {
        result = path;
        CoTaskMemFree(path);
    }
    if (result.empty())
    {
        wchar_t buffer[MAX_PATH] = {};
        DWORD len = GetEnvironmentVariableW(L"APPDATA", buffer, MAX_PATH);
        if (len > 0 && len < MAX_PATH)
            result = buffer;
    }
    if (result.empty())
        return L"settings.ini";
    result += L"\\LoudNorm";
    CreateDirectoryW(result.c_str(), nullptr);
    return result;
}

std::wstring ReadString(const std::wstring& file, const wchar_t* section, const wchar_t* key, const wchar_t* def)
{
    wchar_t buffer[256] = {};
    GetPrivateProfileStringW(section, key, def, buffer, 256, file.c_str());
    return buffer;
}

double ReadDouble(const std::wstring& file, const wchar_t* section, const wchar_t* key, double def)
{
    wchar_t defText[64];
    swprintf_s(defText, L"%.4f", def);
    const std::wstring text = ReadString(file, section, key, defText);
    return wcstod(text.c_str(), nullptr);
}

int ReadInt(const std::wstring& file, const wchar_t* section, const wchar_t* key, int def)
{
    return GetPrivateProfileIntW(section, key, def, file.c_str());
}

void WriteDouble(const std::wstring& file, const wchar_t* section, const wchar_t* key, double value)
{
    wchar_t text[64];
    swprintf_s(text, L"%.4f", value);
    WritePrivateProfileStringW(section, key, text, file.c_str());
}

void WriteInt(const std::wstring& file, const wchar_t* section, const wchar_t* key, int value)
{
    wchar_t text[64];
    swprintf_s(text, L"%d", value);
    WritePrivateProfileStringW(section, key, text, file.c_str());
}

} // namespace

std::wstring SettingsManager::FilePath()
{
    static const std::wstring path = AppDataDir() + L"\\settings.ini";
    return path;
}

Settings SettingsManager::Load()
{
    Settings s;
    const std::wstring file = FilePath();
    if (GetFileAttributesW(file.c_str()) == INVALID_FILE_ATTRIBUTES)
        return s;

    s.targetLufs = ReadDouble(file, L"Loudness", L"TargetLufs", s.targetLufs);
    s.autoEnabled = ReadInt(file, L"Loudness", L"AutoEnabled", s.autoEnabled ? 1 : 0) != 0;
    s.testMode = ReadInt(file, L"Loudness", L"TestMode", s.testMode ? 1 : 0) != 0;

    s.maxGainDb = ReadDouble(file, L"Gain", L"MaxGainDb", s.maxGainDb);
    s.minGainDb = ReadDouble(file, L"Gain", L"MinGainDb", s.minGainDb);
    s.attackMs = ReadDouble(file, L"Gain", L"AttackMs", s.attackMs);
    s.releaseMs = ReadDouble(file, L"Gain", L"ReleaseMs", s.releaseMs);
    s.rateDbPerSec = ReadDouble(file, L"Gain", L"RateDbPerSec", s.rateDbPerSec);
    s.sensitivity = ReadDouble(file, L"Gain", L"Sensitivity", s.sensitivity);
    s.calibrationDb = ReadDouble(file, L"Gain", L"CalibrationDb", s.calibrationDb);
    s.deadZoneDb = ReadDouble(file, L"Gain", L"DeadZoneDb", s.deadZoneDb);

    s.startMinimized = ReadInt(file, L"Window", L"StartMinimized", s.startMinimized ? 1 : 0) != 0;
    s.minimizeToTrayOnClose =
        ReadInt(file, L"Window", L"MinimizeToTrayOnClose", s.minimizeToTrayOnClose ? 1 : 0) != 0;

    // 合法性保护
    s.targetLufs = Clamp(s.targetLufs, -40.0, -5.0);
    s.maxGainDb = Clamp(s.maxGainDb, 0.0, 30.0);
    s.minGainDb = Clamp(s.minGainDb, -40.0, 0.0);
    s.attackMs = Clamp(s.attackMs, 50.0, 10000.0);
    s.releaseMs = Clamp(s.releaseMs, 50.0, 10000.0);
    s.rateDbPerSec = Clamp(s.rateDbPerSec, 0.2, 20.0);
    s.sensitivity = Clamp(s.sensitivity, 0.0, 100.0);
    s.calibrationDb = Clamp(s.calibrationDb, -40.0, 6.0);
    s.deadZoneDb = Clamp(s.deadZoneDb, 0.0, 6.0);
    return s;
}

void SettingsManager::Save(const Settings& s)
{
    const std::wstring file = FilePath();

    WriteDouble(file, L"Loudness", L"TargetLufs", s.targetLufs);
    WriteInt(file, L"Loudness", L"AutoEnabled", s.autoEnabled ? 1 : 0);
    WriteInt(file, L"Loudness", L"TestMode", s.testMode ? 1 : 0);

    WriteDouble(file, L"Gain", L"MaxGainDb", s.maxGainDb);
    WriteDouble(file, L"Gain", L"MinGainDb", s.minGainDb);
    WriteDouble(file, L"Gain", L"AttackMs", s.attackMs);
    WriteDouble(file, L"Gain", L"ReleaseMs", s.releaseMs);
    WriteDouble(file, L"Gain", L"RateDbPerSec", s.rateDbPerSec);
    WriteDouble(file, L"Gain", L"Sensitivity", s.sensitivity);
    WriteDouble(file, L"Gain", L"CalibrationDb", s.calibrationDb);
    WriteDouble(file, L"Gain", L"DeadZoneDb", s.deadZoneDb);

    WriteInt(file, L"Window", L"StartMinimized", s.startMinimized ? 1 : 0);
    WriteInt(file, L"Window", L"MinimizeToTrayOnClose", s.minimizeToTrayOnClose ? 1 : 0);
}

} // namespace ln
