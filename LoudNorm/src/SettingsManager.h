// SettingsManager.h - 配置读写（%APPDATA%\LoudNorm\settings.ini）
#pragma once

#include "Common.h"
#include "Settings.h"

namespace ln {

class SettingsManager
{
public:
    static std::wstring FilePath();
    static Settings Load();
    static void Save(const Settings& settings);
};

} // namespace ln
