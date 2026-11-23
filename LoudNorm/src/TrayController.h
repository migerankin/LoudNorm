// TrayController.h - Windows 系统托盘图标与气泡提示
#pragma once

#include "Common.h"

namespace ln {

class TrayController
{
public:
    TrayController() = default;
    ~TrayController();

    TrayController(const TrayController&) = delete;
    TrayController& operator=(const TrayController&) = delete;

    bool Add(HWND owner, UINT callbackMessage, const std::wstring& tooltip);
    void Remove();
    void UpdateTooltip(const std::wstring& tooltip);
    void ShowBalloon(const std::wstring& title, const std::wstring& text);

private:
    NOTIFYICONDATAW data_ = {};
    bool added_ = false;
};

} // namespace ln
