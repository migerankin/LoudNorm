// MainWindow.cpp
#include "MainWindow.h"

#include "SettingsManager.h"

namespace ln {

namespace {

enum : int
{
    IDC_TARGET = 1001,
    IDC_AUTO,
    IDC_TESTMODE,
    IDC_MAXGAIN,
    IDC_MINGAIN,
    IDC_ATTACK,
    IDC_RELEASE,
    IDC_CALIB,
    IDC_RATE,
    IDC_RATEVAL,
    IDC_SENS,
    IDC_SENSVAL,
    IDC_PAUSE,
    IDC_RESTORE,
    IDC_RESUME,
    IDC_LIST,
    IDC_STATUS,
};

enum : int
{
    IDM_TRAY_SHOW = 40001,
    IDM_TRAY_TOGGLE,
    IDM_TRAY_TESTMODE,
    IDM_TRAY_RESTORE,
    IDM_TRAY_EXIT,
};

constexpr int kTimerId = 1;

std::wstring GetText(HWND hwnd)
{
    if (!hwnd)
        return std::wstring();
    wchar_t buffer[512] = {};
    const int length = GetWindowTextW(hwnd, buffer, 512);
    return std::wstring(buffer, length);
}

double ParseNumber(const std::wstring& text, double fallback)
{
    wchar_t* end = nullptr;
    const double value = wcstod(text.c_str(), &end);
    if (end == text.c_str())
        return fallback;
    return value;
}

} // namespace

// ---------------------------------------------------------------------------
// 窗口创建与消息循环
// ---------------------------------------------------------------------------
bool MainWindow::Create(HINSTANCE instance)
{
    instance_ = instance;
    settings_ = SettingsManager::Load();

    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(WNDCLASSEXW);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = &MainWindow::WindowProcStatic;
    wc.hInstance = instance;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    wc.hbrBackground = GetSysColorBrush(COLOR_BTNFACE);
    wc.lpszClassName = kMainWindowClass;
    wc.lpszMenuName = nullptr;
    RegisterClassExW(&wc);

    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN;
    RECT rect = {0, 0, D(1000), D(700)};
    AdjustWindowRectEx(&rect, style, FALSE, 0);

    hwnd_ = CreateWindowExW(0, kMainWindowClass, kAppTitle, style, CW_USEDEFAULT, CW_USEDEFAULT,
                            rect.right - rect.left, rect.bottom - rect.top, nullptr, nullptr, instance, this);
    if (!hwnd_)
        return false;

    dpi_ = static_cast<int>(GetDpiForWindow(hwnd_));
    if (dpi_ <= 0)
    {
        HDC screen = GetDC(nullptr);
        dpi_ = GetDeviceCaps(screen, LOGPIXELSX);
        ReleaseDC(nullptr, screen);
    }
    if (dpi_ <= 0)
        dpi_ = 96;

    // 按实际 DPI 调整窗口客户区尺寸（布局以 96 DPI 为基准设计）
    RECT desired = {0, 0, D(1000), D(700)};
    AdjustWindowRectEx(&desired, style, FALSE, 0);
    SetWindowPos(hwnd_, nullptr, 0, 0, desired.right - desired.left, desired.bottom - desired.top,
                 SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);

    if (!OnCreate())
    {
        DestroyWindow(hwnd_);
        hwnd_ = nullptr;
        return false;
    }
    return true;
}

void MainWindow::ShowWindowFromSettings()
{
    if (!hwnd_)
        return;
    if (settings_.startMinimized)
    {
        hidden_ = true;
        ShowWindow(hwnd_, SW_HIDE);
    }
    else
    {
        ShowWindow(hwnd_, SW_SHOW);
        UpdateWindow(hwnd_);
    }
}

int MainWindow::Run()
{
    MSG message = {};
    while (GetMessageW(&message, nullptr, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return static_cast<int>(message.wParam);
}

LRESULT CALLBACK MainWindow::WindowProcStatic(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam)
{
    MainWindow* self = nullptr;
    if (message == WM_NCCREATE)
    {
        auto* create = reinterpret_cast<CREATESTRUCTW*>(lParam);
        self = static_cast<MainWindow*>(create->lpCreateParams);
        if (self)
        {
            self->hwnd_ = hwnd;
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        }
    }
    else
    {
        self = reinterpret_cast<MainWindow*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    }

    if (self)
        return self->WindowProc(hwnd, message, wParam, lParam);
    return DefWindowProcW(hwnd, message, wParam, lParam);
}

LRESULT MainWindow::WindowProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam)
{
    switch (message)
    {
    case WM_CREATE:
        return 0;

    case WM_TIMER:
        if (wParam == kTimerId)
            OnTimer();
        return 0;

    case WM_COMMAND:
        OnCommand(LOWORD(wParam), HIWORD(wParam));
        return 0;

    case WM_HSCROLL:
        OnHorizontalScroll(reinterpret_cast<HWND>(lParam));
        return 0;

    case WM_CTLCOLORSTATIC:
    {
        HDC dc = reinterpret_cast<HDC>(wParam);
        SetBkMode(dc, TRANSPARENT);
        return reinterpret_cast<LRESULT>(GetSysColorBrush(COLOR_BTNFACE));
    }

    case kTrayCallbackMessage:
        if (lParam == WM_RBUTTONUP || lParam == WM_CONTEXTMENU)
            ShowTrayMenu();
        else if (lParam == WM_LBUTTONDBLCLK)
            RestoreFromTray();
        return 0;

    case kShowWindowMessage:
        RestoreFromTray();
        return 0;

    case WM_CLOSE:
        if (!exiting_ && settings_.minimizeToTrayOnClose)
            HideToTray();
        else
            ExitApplication();
        return 0;

    case WM_ENDSESSION:
        if (wParam)
            engine_.Stop();
        return 0;

    case WM_DESTROY:
        KillTimer(hwnd, kTimerId);
        if (font_)
            DeleteObject(font_);
        if (fontBold_)
            DeleteObject(fontBold_);
        if (fontSmall_)
            DeleteObject(fontSmall_);
        PostQuitMessage(0);
        return 0;

    default:
        break;
    }
    return DefWindowProcW(hwnd, message, wParam, lParam);
}

// ---------------------------------------------------------------------------
// 界面构建
// ---------------------------------------------------------------------------
bool MainWindow::OnCreate()
{
    CreateFonts();
    CreateControls();
    LoadSettingsToControls();

    engine_.ApplySettings(settings_);
    engine_.Start();

    tray_.Add(hwnd_, kTrayCallbackMessage, L"LoudNorm - 绝对响度自动均衡");
    UpdateTrayTooltip();

    SetTimer(hwnd_, kTimerId, 200, nullptr);
    return true;
}

void MainWindow::CreateFonts()
{
    const int height = -MulDiv(9, dpi_, 72);
    font_ = CreateFontW(height, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                        DEFAULT_PITCH | FF_DONTCARE, L"Microsoft YaHei UI");
    fontBold_ = CreateFontW(-MulDiv(11, dpi_, 72), 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
                            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                            DEFAULT_PITCH | FF_DONTCARE, L"Microsoft YaHei UI");
    fontSmall_ = CreateFontW(-MulDiv(8, dpi_, 72), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                             DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                             DEFAULT_PITCH | FF_DONTCARE, L"Microsoft YaHei UI");
}

void MainWindow::CreateControls()
{
    const auto make = [this](const wchar_t* className, const wchar_t* text, DWORD style, int id,
                             int x, int y, int w, int h, HFONT font) -> HWND {
        HWND control = CreateWindowExW(0, className, text, WS_CHILD | WS_VISIBLE | style, D(x), D(y),
                                       D(w), D(h), hwnd_, reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),
                                       instance_, nullptr);
        if (control && font)
            SendMessageW(control, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        return control;
    };

    const auto label = [&](const wchar_t* text, int x, int y, int w, int h, HFONT font) {
        make(L"STATIC", text, SS_LEFT | SS_CENTERIMAGE, 0, x, y, w, h, font);
    };

    // ---- 目标响度 ----
    make(L"BUTTON", L"绝对目标响度（唯一基准）", BS_GROUPBOX, 0, 12, 10, 976, 62, font_);
    label(L"目标响度 (LUFS)", 24, 34, 120, 20, font_);

    HWND target = make(L"ComboBox", L"", CBS_DROPDOWN | CBS_AUTOHSCROLL | WS_VSCROLL, IDC_TARGET,
                       150, 30, 160, 260, font_);
    int presetCount = 0;
    const LoudnessPreset* presets = LoudnessPresets(presetCount);
    for (int i = 0; i < presetCount; ++i)
        SendMessageW(target, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(presets[i].label));

    label(L"每个应用都以该绝对值独立测量、独立调整，互不作为参考源", 322, 34, 310, 20, fontSmall_);
    make(L"BUTTON", L"启用自动均衡", BS_AUTOCHECKBOX, IDC_AUTO, 640, 32, 140, 22, font_);
    make(L"BUTTON", L"测试模式（只计算，不改音量）", BS_AUTOCHECKBOX, IDC_TESTMODE, 790, 32, 190, 22, font_);

    // ---- 增益参数 ----
    make(L"BUTTON", L"自动增益 / 平滑参数", BS_GROUPBOX, 0, 12, 80, 976, 136, font_);

    label(L"最大增益 (dB)", 24, 110, 90, 20, font_);
    make(L"EDIT", L"", ES_AUTOHSCROLL | ES_RIGHT, IDC_MAXGAIN, 120, 106, 60, 22, font_);

    label(L"最大衰减 (dB)", 196, 110, 90, 20, font_);
    make(L"EDIT", L"", ES_AUTOHSCROLL | ES_RIGHT, IDC_MINGAIN, 292, 106, 60, 22, font_);

    label(L"Attack (ms)", 368, 110, 80, 20, font_);
    make(L"EDIT", L"", ES_AUTOHSCROLL | ES_RIGHT, IDC_ATTACK, 452, 106, 60, 22, font_);

    label(L"Release (ms)", 528, 110, 84, 20, font_);
    make(L"EDIT", L"", ES_AUTOHSCROLL | ES_RIGHT, IDC_RELEASE, 616, 106, 60, 22, font_);

    label(L"响度校准 (dB)", 692, 110, 90, 20, font_);
    make(L"EDIT", L"", ES_AUTOHSCROLL | ES_RIGHT, IDC_CALIB, 788, 106, 60, 22, font_);

    label(L"调整速度", 24, 150, 64, 20, font_);
    HWND rate = make(TRACKBAR_CLASSW, L"", TBS_HORZ | TBS_NOTICKS, IDC_RATE, 92, 142, 230, 30, font_);
    SendMessageW(rate, TBM_SETRANGE, TRUE, MAKELPARAM(0, 100));
    make(L"STATIC", L"", SS_LEFT | SS_CENTERIMAGE, IDC_RATEVAL, 330, 150, 110, 20, font_);

    label(L"灵敏度", 452, 150, 50, 20, font_);
    HWND sens = make(TRACKBAR_CLASSW, L"", TBS_HORZ | TBS_NOTICKS, IDC_SENS, 508, 142, 230, 30, font_);
    SendMessageW(sens, TBM_SETRANGE, TRUE, MAKELPARAM(0, 100));
    make(L"STATIC", L"", SS_LEFT | SS_CENTERIMAGE, IDC_SENSVAL, 746, 150, 150, 20, font_);

    label(L"提示：调整速度同时限制每秒最大 dB 变化，灵敏度决定响度统计窗口", 24, 178, 800, 20, fontSmall_);

    // ---- 操作按钮 ----
    make(L"BUTTON", L"暂停自动均衡", BS_PUSHBUTTON, IDC_PAUSE, 12, 226, 140, 30, font_);
    make(L"BUTTON", L"恢复所有应用原始音量", BS_PUSHBUTTON, IDC_RESTORE, 164, 226, 190, 30, font_);
    make(L"BUTTON", L"恢复自动接管", BS_PUSHBUTTON, IDC_RESUME, 366, 226, 160, 30, font_);
    label(L"手动拖动某应用音量后，程序会交出该应用的控制权，可点“恢复自动接管”", 540, 232, 448, 20, fontSmall_);

    // ---- 应用列表 ----
    HWND list = make(L"SysListView32", L"",
                     LVS_REPORT | LVS_SINGLESEL | LVS_SHOWSELALWAYS | WS_BORDER, IDC_LIST, 12, 268, 976, 380,
                     font_);
    ListView_SetExtendedListViewStyle(list, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER | LVS_EX_GRIDLINES);

    struct Column
    {
        const wchar_t* text;
        int width;
    };
    const Column columns[] = {
        {L"应用名称", 200},   {L"应用音量", 80},        {L"估算响度 (LUFS)", 130}, {L"目标 (LUFS)", 95},
        {L"自动增益 (dB)", 105}, {L"理论调整 (dB)", 105}, {L"状态", 140},
    };
    for (int i = 0; i < static_cast<int>(sizeof(columns) / sizeof(columns[0])); ++i)
    {
        LVCOLUMNW column = {};
        column.mask = LVCF_TEXT | LVCF_WIDTH | LVCF_SUBITEM;
        column.iSubItem = i;
        column.pszText = const_cast<wchar_t*>(columns[i].text);
        column.cx = D(columns[i].width);
        ListView_InsertColumn(list, i, &column);
    }

    // ---- 状态栏 ----
    make(L"STATIC", L"", SS_LEFT | SS_CENTERIMAGE | SS_ENDELLIPSIS, IDC_STATUS, 12, 656, 976, 22, fontSmall_);

    (void)fontBold_;
}

void MainWindow::LoadSettingsToControls()
{
    SetWindowTextW(Control(IDC_TARGET), FormatW(L"%.1f", settings_.targetLufs).c_str());
    SendMessageW(Control(IDC_AUTO), BM_SETCHECK, settings_.autoEnabled ? BST_CHECKED : BST_UNCHECKED, 0);
    SendMessageW(Control(IDC_TESTMODE), BM_SETCHECK, settings_.testMode ? BST_CHECKED : BST_UNCHECKED, 0);

    SetWindowTextW(Control(IDC_MAXGAIN), FormatW(L"%.1f", settings_.maxGainDb).c_str());
    SetWindowTextW(Control(IDC_MINGAIN), FormatW(L"%.1f", settings_.minGainDb).c_str());
    SetWindowTextW(Control(IDC_ATTACK), FormatW(L"%.0f", settings_.attackMs).c_str());
    SetWindowTextW(Control(IDC_RELEASE), FormatW(L"%.0f", settings_.releaseMs).c_str());
    SetWindowTextW(Control(IDC_CALIB), FormatW(L"%.1f", settings_.calibrationDb).c_str());

    SendMessageW(Control(IDC_RATE), TBM_SETPOS, TRUE,
                 static_cast<LPARAM>(RateDbPerSecToSpeed(settings_.rateDbPerSec)));
    SendMessageW(Control(IDC_SENS), TBM_SETPOS, TRUE,
                 static_cast<LPARAM>(Clamp(settings_.sensitivity, 0.0, 100.0)));

    UpdateDynamicLabels();
}

void MainWindow::CollectSettingsAndApply(bool saveToDisk)
{
    settings_.targetLufs =
        Clamp(ParseNumber(GetText(Control(IDC_TARGET)), settings_.targetLufs), -40.0, -5.0);
    settings_.autoEnabled =
        SendMessageW(Control(IDC_AUTO), BM_GETCHECK, 0, 0) == BST_CHECKED;
    settings_.testMode =
        SendMessageW(Control(IDC_TESTMODE), BM_GETCHECK, 0, 0) == BST_CHECKED;
    settings_.maxGainDb = Clamp(ParseNumber(GetText(Control(IDC_MAXGAIN)), settings_.maxGainDb), 0.0, 30.0);
    settings_.minGainDb =
        Clamp(ParseNumber(GetText(Control(IDC_MINGAIN)), settings_.minGainDb), -40.0, 0.0);
    settings_.attackMs = Clamp(ParseNumber(GetText(Control(IDC_ATTACK)), settings_.attackMs), 50.0, 10000.0);
    settings_.releaseMs =
        Clamp(ParseNumber(GetText(Control(IDC_RELEASE)), settings_.releaseMs), 50.0, 10000.0);
    settings_.calibrationDb =
        Clamp(ParseNumber(GetText(Control(IDC_CALIB)), settings_.calibrationDb), -40.0, 6.0);
    settings_.sensitivity =
        static_cast<double>(SendMessageW(Control(IDC_SENS), TBM_GETPOS, 0, 0));
    settings_.rateDbPerSec =
        SpeedToRateDbPerSec(static_cast<double>(SendMessageW(Control(IDC_RATE), TBM_GETPOS, 0, 0)));

    if (settings_.minGainDb > settings_.maxGainDb)
        settings_.minGainDb = settings_.maxGainDb;

    engine_.ApplySettings(settings_);
    if (saveToDisk)
        SettingsManager::Save(settings_);

    UpdateDynamicLabels();
    UpdateTrayTooltip();
}

void MainWindow::UpdateDynamicLabels()
{
    SetWindowTextW(GetDlgItem(hwnd_, IDC_RATEVAL),
                   FormatW(L"%.1f dB/s", settings_.rateDbPerSec).c_str());
    SetWindowTextW(GetDlgItem(hwnd_, IDC_SENSVAL),
                   FormatW(L"窗口 %.0f ms", SensitivityToWindowMs(settings_.sensitivity)).c_str());
    SetWindowTextW(Control(IDC_PAUSE), engine_.IsPaused() ? L"继续自动均衡" : L"暂停自动均衡");
}

// ---------------------------------------------------------------------------
// 事件处理
// ---------------------------------------------------------------------------
void MainWindow::OnTimer()
{
    UpdateList();

    const std::wstring status = engine_.StatusText();
    if (GetText(Control(IDC_STATUS)) != status)
        SetWindowTextW(Control(IDC_STATUS), status.c_str());
}

void MainWindow::OnCommand(int id, int code)
{
    switch (id)
    {
    case IDC_TARGET:
        if (code == CBN_SELCHANGE)
        {
            const int index = static_cast<int>(SendMessageW(Control(IDC_TARGET), CB_GETCURSEL, 0, 0));
            int presetCount = 0;
            const LoudnessPreset* presets = LoudnessPresets(presetCount);
            if (index >= 0 && index < presetCount)
            {
                settings_.targetLufs = presets[index].value;
                SetWindowTextW(Control(IDC_TARGET), FormatW(L"%.1f", settings_.targetLufs).c_str());
            }
            CollectSettingsAndApply(true);
        }
        else if (code == CBN_KILLFOCUS)
        {
            CollectSettingsAndApply(true);
            SetWindowTextW(Control(IDC_TARGET), FormatW(L"%.1f", settings_.targetLufs).c_str());
        }
        else if (code == CBN_EDITCHANGE)
        {
            const double value = ParseNumber(GetText(Control(IDC_TARGET)), settings_.targetLufs);
            if (value >= -40.0 && value <= -5.0)
            {
                settings_.targetLufs = value;
                engine_.ApplySettings(settings_);
            }
        }
        break;

    case IDC_AUTO:
    case IDC_TESTMODE:
        CollectSettingsAndApply(true);
        break;

    case IDC_MAXGAIN:
    case IDC_MINGAIN:
    case IDC_ATTACK:
    case IDC_RELEASE:
    case IDC_CALIB:
        if (code == EN_KILLFOCUS)
            CollectSettingsAndApply(true);
        break;

    case IDC_PAUSE:
        engine_.SetPaused(!engine_.IsPaused());
        UpdateDynamicLabels();
        UpdateTrayTooltip();
        break;

    case IDC_RESTORE:
        engine_.RestoreAllNow();
        break;

    case IDC_RESUME:
        engine_.ResumeManualApps();
        break;

    case IDM_TRAY_SHOW:
        RestoreFromTray();
        break;

    case IDM_TRAY_TOGGLE:
        if (!settings_.autoEnabled)
        {
            settings_.autoEnabled = true;
            engine_.SetPaused(false);
        }
        else
        {
            engine_.SetPaused(!engine_.IsPaused());
        }
        LoadSettingsToControls();
        CollectSettingsAndApply(true);
        break;

    case IDM_TRAY_TESTMODE:
        settings_.testMode = !settings_.testMode;
        LoadSettingsToControls();
        CollectSettingsAndApply(true);
        break;

    case IDM_TRAY_RESTORE:
        engine_.RestoreAllNow();
        break;

    case IDM_TRAY_EXIT:
        ExitApplication();
        break;

    default:
        break;
    }
}

void MainWindow::OnHorizontalScroll(HWND source)
{
    if (!source)
        return;
    const int id = GetDlgCtrlID(source);
    if (id == IDC_RATE || id == IDC_SENS)
        CollectSettingsAndApply(true);
}

// ---------------------------------------------------------------------------
// 列表 / 托盘
// ---------------------------------------------------------------------------
void MainWindow::UpdateList()
{
    HWND list = Control(IDC_LIST);
    if (!list)
        return;

    const std::vector<AppSnapshot> snapshots = engine_.Snapshots();
    const int desired = static_cast<int>(snapshots.size());
    int current = ListView_GetItemCount(list);

    while (current > desired)
    {
        ListView_DeleteItem(list, current - 1);
        --current;
    }

    LVITEMW item = {};
    item.mask = LVIF_TEXT;
    item.pszText = const_cast<wchar_t*>(L"");
    while (current < desired)
    {
        item.iItem = current;
        ListView_InsertItem(list, &item);
        ++current;
    }

    rowCache_.resize(snapshots.size());

    for (int row = 0; row < desired; ++row)
    {
        const AppSnapshot& snapshot = snapshots[row];
        std::vector<std::wstring> cells;
        cells.push_back(snapshot.name);
        cells.push_back(FormatW(L"%.0f%%", snapshot.volumePercent));
        cells.push_back(FormatLufs(snapshot.estimatedLufs));
        cells.push_back(FormatLufs(snapshot.targetLufs));
        cells.push_back(FormatDb(snapshot.appliedGainDb));
        cells.push_back(FormatDb(snapshot.theoreticalGainDb));
        cells.push_back(AppStateText(snapshot.state));

        if (rowCache_[row] == cells)
            continue;
        rowCache_[row] = cells;

        for (int column = 0; column < static_cast<int>(cells.size()); ++column)
            ListView_SetItemText(list, row, column, const_cast<wchar_t*>(cells[column].c_str()));
    }
}

void MainWindow::UpdateTrayTooltip()
{
    const wchar_t* state = L"运行中";
    if (!settings_.autoEnabled)
        state = L"已关闭";
    else if (settings_.testMode)
        state = L"测试模式";
    else if (engine_.IsPaused())
        state = L"已暂停";
    tray_.UpdateTooltip(FormatW(L"LoudNorm · 目标 %.1f LUFS · %s", settings_.targetLufs, state));
}

void MainWindow::ShowTrayMenu()
{
    HMENU menu = CreatePopupMenu();
    if (!menu)
        return;

    const bool paused = engine_.IsPaused();
    const bool running = settings_.autoEnabled && !paused;

    AppendMenuW(menu, MF_STRING, IDM_TRAY_SHOW, L"打开主窗口");
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING | (running ? MF_CHECKED : MF_UNCHECKED), IDM_TRAY_TOGGLE,
                running ? L"暂停自动均衡" : L"开启自动均衡");
    AppendMenuW(menu, MF_STRING | (settings_.testMode ? MF_CHECKED : MF_UNCHECKED), IDM_TRAY_TESTMODE,
                L"测试模式");
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, IDM_TRAY_RESTORE, L"恢复所有应用原始音量");
    AppendMenuW(menu, MF_STRING, IDM_TRAY_EXIT, L"退出程序");

    POINT cursor = {};
    GetCursorPos(&cursor);
    SetForegroundWindow(hwnd_);
    TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_LEFTALIGN, cursor.x, cursor.y, 0, hwnd_, nullptr);
    PostMessageW(hwnd_, WM_NULL, 0, 0);
    DestroyMenu(menu);
}

void MainWindow::HideToTray()
{
    if (!hwnd_)
        return;
    ShowWindow(hwnd_, SW_HIDE);
    hidden_ = true;
    if (!trayHintShown_)
    {
        tray_.ShowBalloon(L"LoudNorm 仍在后台运行", L"自动均衡继续生效。右键托盘图标可暂停或退出。");
        trayHintShown_ = true;
    }
}

void MainWindow::RestoreFromTray()
{
    if (!hwnd_)
        return;
    ShowWindow(hwnd_, SW_SHOW);
    ShowWindow(hwnd_, SW_RESTORE);
    SetForegroundWindow(hwnd_);
    hidden_ = false;
}

void MainWindow::ExitApplication()
{
    if (exiting_)
        return;
    exiting_ = true;

    KillTimer(hwnd_, kTimerId);
    // 停止自动增益控制、恢复所有应用原始音量、释放音频会话对象
    engine_.Stop();
    tray_.Remove();

    if (hwnd_)
        DestroyWindow(hwnd_);
}

} // namespace ln
