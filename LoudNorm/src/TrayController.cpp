// TrayController.cpp
#include "TrayController.h"

namespace ln {

TrayController::~TrayController()
{
    Remove();
}

bool TrayController::Add(HWND owner, UINT callbackMessage, const std::wstring& tooltip)
{
    data_ = {};
    data_.cbSize = sizeof(NOTIFYICONDATAW);
    data_.hWnd = owner;
    data_.uID = 1;
    data_.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    data_.uCallbackMessage = callbackMessage;
    data_.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    wcsncpy_s(data_.szTip, tooltip.c_str(), _TRUNCATE);

    added_ = Shell_NotifyIconW(NIM_ADD, &data_) != FALSE;
    return added_;
}

void TrayController::Remove()
{
    if (!added_)
        return;
    Shell_NotifyIconW(NIM_DELETE, &data_);
    added_ = false;
}

void TrayController::UpdateTooltip(const std::wstring& tooltip)
{
    if (!added_)
        return;
    data_.uFlags = NIF_TIP;
    wcsncpy_s(data_.szTip, tooltip.c_str(), _TRUNCATE);
    Shell_NotifyIconW(NIM_MODIFY, &data_);
}

void TrayController::ShowBalloon(const std::wstring& title, const std::wstring& text)
{
    if (!added_)
        return;
    data_.uFlags = NIF_INFO;
    data_.dwInfoFlags = NIIF_INFO;
    wcsncpy_s(data_.szInfoTitle, title.c_str(), _TRUNCATE);
    wcsncpy_s(data_.szInfo, text.c_str(), _TRUNCATE);
    Shell_NotifyIconW(NIM_MODIFY, &data_);
}

} // namespace ln
