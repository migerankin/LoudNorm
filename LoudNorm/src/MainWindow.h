// MainWindow.h - 主窗口（Win32 原生控件）+ 系统托盘交互
#pragma once

#include "AudioEngine.h"
#include "Common.h"
#include "Settings.h"
#include "TrayController.h"

namespace ln {

class MainWindow
{
public:
    bool Create(HINSTANCE instance);
    void ShowWindowFromSettings();
    int Run();

private:
    static LRESULT CALLBACK WindowProcStatic(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam);
    LRESULT WindowProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam);

    bool OnCreate();
    void CreateFonts();
    void CreateControls();
    void LoadSettingsToControls();
    void CollectSettingsAndApply(bool saveToDisk);
    void UpdateDynamicLabels();

    void OnTimer();
    void OnCommand(int id, int code);
    void OnHorizontalScroll(HWND source);
    void UpdateList();
    void UpdateTrayTooltip();
    void ShowTrayMenu();

    void HideToTray();
    void RestoreFromTray();
    void ExitApplication();

    int D(int value) const { return MulDiv(value, dpi_, 96); }

    HWND Control(int id) const { return GetDlgItem(hwnd_, id); }

    HINSTANCE instance_ = nullptr;
    HWND hwnd_ = nullptr;
    int dpi_ = 96;

    AudioEngine engine_;
    Settings settings_;
    TrayController tray_;

    HFONT font_ = nullptr;
    HFONT fontBold_ = nullptr;
    HFONT fontSmall_ = nullptr;

    bool exiting_ = false;
    bool hidden_ = false;
    bool trayHintShown_ = false;

    std::vector<std::vector<std::wstring>> rowCache_;
};

} // namespace ln
