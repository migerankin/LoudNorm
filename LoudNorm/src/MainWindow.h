// MainWindow.h - 主窗口（调音台风格自绘 Win32 界面）+ 系统托盘
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
    void CreateControls();
    void LoadSettingsToControls();
    void CollectSettingsAndApply(bool saveToDisk);
    void UpdateDynamicLabels();

    void ApplyTarget(double value, bool saveToDisk);
    void NudgeTarget(double delta);
    void ShowTargetPresetMenu();

    void OnTimer();
    void OnCommand(int id, int code);
    void OnHorizontalScroll(HWND source);
    void OnDrawItem(const DRAWITEMSTRUCT& item);
    LRESULT OnListCustomDraw(const NMLVCUSTOMDRAW* customDraw);
    void OnPaint();
    void PaintConsole(HDC dc, const RECT& client);
    void UpdateList();
    void UpdateTrayTooltip();
    void ShowTrayMenu();

    void HideToTray();
    void RestoreFromTray();
    void ExitApplication();

    int D(int value) const { return MulDiv(value, dpi_, 96); }
    RECT DRect(int left, int top, int right, int bottom) const;
    HWND Control(int id) const { return GetDlgItem(hwnd_, id); }

    HINSTANCE instance_ = nullptr;
    HWND hwnd_ = nullptr;
    int dpi_ = 96;

    AudioEngine engine_;
    Settings settings_;
    TrayController tray_;

    bool exiting_ = false;
    bool hidden_ = false;
    bool trayHintShown_ = false;
    bool settingsDirty_ = false;

    std::vector<AppSnapshot> lastSnapshots_;
    std::vector<std::vector<std::wstring>> rowCache_;
};

} // namespace ln
