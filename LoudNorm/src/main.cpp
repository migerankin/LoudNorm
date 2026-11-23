// main.cpp - 程序入口：单实例、DPI 感知、公共控件初始化、COM 初始化
#include "Common.h"
#include "MainWindow.h"

#pragma comment(linker, \
    "\"/manifestdependency:type='Win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")

namespace {

constexpr wchar_t kMutexName[] = L"Global\\LoudNorm.SingleInstance.7A52F9E1";

void EnableDpiAwareness()
{
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (!user32)
        return;

    using SetProcessDpiAwarenessContextFn = BOOL(WINAPI*)(DPI_AWARENESS_CONTEXT);
    auto setContext = reinterpret_cast<SetProcessDpiAwarenessContextFn>(
        GetProcAddress(user32, "SetProcessDpiAwarenessContext"));
    if (setContext && setContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
        return;

    using SetProcessDpiAwareFn = BOOL(WINAPI*)();
    auto setAware = reinterpret_cast<SetProcessDpiAwareFn>(GetProcAddress(user32, "SetProcessDPIAware"));
    if (setAware)
        setAware();
}

} // namespace

int APIENTRY wWinMain(HINSTANCE hInstance, HINSTANCE, LPWSTR, int)
{
    HANDLE mutex = CreateMutexW(nullptr, TRUE, kMutexName);
    if (mutex && GetLastError() == ERROR_ALREADY_EXISTS)
    {
        // 已有实例：唤醒主窗口后退出
        if (HWND existing = FindWindowW(ln::kMainWindowClass, nullptr))
            PostMessageW(existing, ln::kShowWindowMessage, 0, 0);
        CloseHandle(mutex);
        return 0;
    }

    EnableDpiAwareness();

    INITCOMMONCONTROLSEX controls = {};
    controls.dwSize = sizeof(INITCOMMONCONTROLSEX);
    controls.dwICC = ICC_WIN95_CLASSES | ICC_BAR_CLASSES | ICC_LISTVIEW_CLASSES | ICC_STANDARD_CLASSES;
    InitCommonControlsEx(&controls);

    const HRESULT comResult = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);

    int exitCode = 1;
    {
        ln::MainWindow window;
        if (window.Create(hInstance))
        {
            window.ShowWindowFromSettings();
            exitCode = window.Run();
        }
    }

    if (SUCCEEDED(comResult))
        CoUninitialize();

    if (mutex)
    {
        ReleaseMutex(mutex);
        CloseHandle(mutex);
    }
    return exitCode;
}
