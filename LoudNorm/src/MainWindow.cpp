// MainWindow.cpp - 录音棚调音台 / 太空复古风格自绘界面
#include "MainWindow.h"

#include "FaderControl.h"
#include "SettingsManager.h"
#include "Theme.h"

#include <uxtheme.h>

#pragma comment(lib, "uxtheme.lib")

namespace ln {

namespace {

// ---- 控件 ID ----
enum : int
{
    IDC_TARGET_EDIT = 1001,
    IDC_TARGET_MINUS,
    IDC_TARGET_PLUS,
    IDC_TARGET_PRESET,
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
    IDM_PRESET_BASE = 40200,
};

constexpr int kTimerId = 1;

// ---- 布局（96 DPI 设计坐标）----
constexpr int kClientWidth = 1000;
constexpr int kClientHeight = 700;

constexpr int kHeaderTop = 0, kHeaderBottom = 62;
constexpr int kPlateATop = 72, kPlateABottom = 142;
constexpr int kPlateBTop = 150, kPlateBBottom = 300;
constexpr int kPlateCTop = 308, kPlateCBottom = 352;
constexpr int kPlateDTop = 360, kPlateDBottom = 668;
constexpr int kStatusTop = 672, kStatusBottom = 694;

constexpr int kColumnLevel = 1;

struct EditSpec
{
    int id;
    int left, top, right, bottom;
};

// 数值输入框位置（同时用于“内凹显示窗”的绘制）
constexpr EditSpec kEditSpecs[] = {
    {IDC_TARGET_EDIT, 30, 102, 146, 128},  {IDC_MAXGAIN, 120, 182, 182, 206},
    {IDC_MINGAIN, 300, 182, 362, 206},     {IDC_ATTACK, 466, 182, 528, 206},
    {IDC_RELEASE, 630, 182, 692, 206},     {IDC_CALIB, 796, 182, 858, 206},
};

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

// 目标响度步进：默认 0.5 dB，按住 Ctrl 为 0.1 dB，按住 Shift 为 5 dB
double TargetStep()
{
    if (GetKeyState(VK_CONTROL) < 0)
        return 0.1;
    if (GetKeyState(VK_SHIFT) < 0)
        return 5.0;
    return 0.5;
}

// 罗盘 / 星空般的背景斑点
void PaintStarField(HDC dc, const RECT& rc)
{
    unsigned int seed = 0x1F2E3D4Cu;
    const int width = std::max(1, static_cast<int>(rc.right - rc.left));
    const int height = std::max(1, static_cast<int>(rc.bottom - rc.top));

    for (int i = 0; i < 240; ++i)
    {
        seed = seed * 1664525u + 1013904223u;
        const int x = rc.left + static_cast<int>(seed % static_cast<unsigned int>(width));
        seed = seed * 1664525u + 1013904223u;
        const int y = rc.top + static_cast<int>(seed % static_cast<unsigned int>(height));
        seed = seed * 1664525u + 1013904223u;

        const int brightness = 20 + static_cast<int>((seed >> 13) % 30);
        SetPixelV(dc, x, y, RGB(brightness, brightness + 4, brightness + 12));
    }
}

void DrawConsoleButton(HDC dc, const RECT& rc, const std::wstring& text, bool pressed, bool accent)
{
    theme::FillSolid(dc, rc, pressed ? RGB(17, 21, 27) : RGB(34, 41, 51));

    RECT top = {rc.left + 1, rc.top + 1, rc.right - 1, rc.top + 2};
    theme::FillSolid(dc, top, pressed ? RGB(11, 14, 18) : RGB(78, 89, 105));

    RECT bottom = {rc.left + 1, rc.bottom - 2, rc.right - 1, rc.bottom - 1};
    theme::FillSolid(dc, bottom, pressed ? RGB(62, 72, 86) : RGB(7, 9, 12));

    theme::DrawOutline(dc, rc, accent ? theme::kAmberDim : RGB(56, 64, 78));

    RECT textRect = rc;
    if (pressed)
        OffsetRect(&textRect, 0, 1);

    HGDIOBJ oldFont = SelectObject(dc, theme::FontUi());
    theme::DrawTextSimple(dc, text, textRect, pressed ? theme::kAmber : theme::kCream,
                          DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
    SelectObject(dc, oldFont);
}

void DrawLedToggle(HDC dc, const RECT& rc, const std::wstring& text, bool on, COLORREF color)
{
    const int centerY = (rc.top + rc.bottom) / 2;
    const int centerX = rc.left + 9;

    theme::DrawLed(dc, centerX, centerY, 5, color, on);

    RECT textRect = rc;
    textRect.left = centerX + 13;
    HGDIOBJ oldFont = SelectObject(dc, theme::FontUi());
    theme::DrawTextSimple(dc, text, textRect, on ? theme::kCream : theme::kDim,
                          DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
    SelectObject(dc, oldFont);
}

// 表头（ListView 的 Header 子类化后自绘）
LRESULT CALLBACK ListHeaderProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam,
                                UINT_PTR subclassId, DWORD_PTR refData)
{
    UNREFERENCED_PARAMETER(subclassId);
    UNREFERENCED_PARAMETER(refData);

    switch (message)
    {
    case WM_ERASEBKGND:
        return 1;

    case WM_PAINT:
    {
        PAINTSTRUCT ps = {};
        HDC dc = BeginPaint(hwnd, &ps);

        RECT client = {};
        GetClientRect(hwnd, &client);
        theme::FillVerticalGradient(dc, client, theme::kHeaderBar, RGB(19, 23, 30));

        const int count = Header_GetItemCount(hwnd);
        HGDIOBJ oldFont = SelectObject(dc, theme::FontSmall());

        for (int i = 0; i < count; ++i)
        {
            RECT itemRect = {};
            if (!Header_GetItemRect(hwnd, i, &itemRect))
                continue;

            wchar_t text[128] = {};
            HDITEMW item = {};
            item.mask = HDI_TEXT;
            item.pszText = text;
            item.cchTextMax = 128;
            Header_GetItem(hwnd, i, &item);

            RECT textRect = itemRect;
            textRect.left += 10;
            theme::DrawTextSimple(dc, text, textRect, theme::kAmberDim,
                                  DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);

            RECT separator = {itemRect.right - 1, itemRect.top + 6, itemRect.right, itemRect.bottom - 5};
            theme::FillSolid(dc, separator, RGB(48, 57, 70));
        }

        SelectObject(dc, oldFont);

        RECT bottomLine = {client.left, client.bottom - 1, client.right, client.bottom};
        theme::FillSolid(dc, bottomLine, theme::kAmberDeep);

        EndPaint(hwnd, &ps);
        return 0;
    }

    default:
        break;
    }

    return DefSubclassProc(hwnd, message, wParam, lParam);
}

} // namespace

// ---------------------------------------------------------------------------
// 窗口骨架
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
    wc.hbrBackground = nullptr;
    wc.lpszClassName = kMainWindowClass;
    wc.lpszMenuName = nullptr;
    RegisterClassExW(&wc);

    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN;
    RECT rect = {0, 0, D(kClientWidth), D(kClientHeight)};
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

    RECT desired = {0, 0, D(kClientWidth), D(kClientHeight)};
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

RECT MainWindow::DRect(int left, int top, int right, int bottom) const
{
    RECT rc = {D(left), D(top), D(right), D(bottom)};
    return rc;
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

    case WM_ERASEBKGND:
        return 1;

    case WM_PAINT:
        OnPaint();
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

    case WM_DRAWITEM:
        OnDrawItem(*reinterpret_cast<DRAWITEMSTRUCT*>(lParam));
        return TRUE;

    case WM_NOTIFY:
    {
        auto* header = reinterpret_cast<NMHDR*>(lParam);
        if (header && header->code == NM_CUSTOMDRAW && header->hwndFrom == Control(IDC_LIST))
            return OnListCustomDraw(reinterpret_cast<NMLVCUSTOMDRAW*>(lParam));
        return 0;
    }

    case WM_CTLCOLORSTATIC:
    {
        HDC dc = reinterpret_cast<HDC>(wParam);
        HWND control = reinterpret_cast<HWND>(lParam);
        const int id = GetDlgCtrlID(control);
        const bool readout = (id == IDC_STATUS || id == IDC_RATEVAL || id == IDC_SENSVAL);
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, readout ? theme::kAmber : theme::kDim);
        return reinterpret_cast<LRESULT>(theme::BrushPanel());
    }

    case WM_CTLCOLOREDIT:
    {
        HDC dc = reinterpret_cast<HDC>(wParam);
        SetBkMode(dc, OPAQUE);
        SetBkColor(dc, theme::kWell);
        SetTextColor(dc, theme::kAmber);
        return reinterpret_cast<LRESULT>(theme::BrushWell());
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
        theme::Destroy();
        PostQuitMessage(0);
        return 0;

    default:
        break;
    }
    return DefWindowProcW(hwnd, message, wParam, lParam);
}

// ---------------------------------------------------------------------------
// 构建
// ---------------------------------------------------------------------------
bool MainWindow::OnCreate()
{
    theme::Create(dpi_);
    RegisterFaderClass(instance_);

    CreateControls();
    LoadSettingsToControls();

    engine_.ApplySettings(settings_);
    engine_.Start();

    tray_.Add(hwnd_, kTrayCallbackMessage, L"LoudNorm - 绝对响度自动均衡");
    UpdateTrayTooltip();

    SetTimer(hwnd_, kTimerId, 120, nullptr);
    return true;
}

void MainWindow::CreateControls()
{
    const auto make = [this](const wchar_t* className, const wchar_t* text, DWORD style, int id,
                             int left, int top, int width, int height, HFONT font) -> HWND {
        HWND control = CreateWindowExW(0, className, text, WS_CHILD | WS_VISIBLE | style, D(left), D(top),
                                       D(width), D(height), hwnd_,
                                       reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), instance_, nullptr);
        if (control && font)
            SendMessageW(control, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        return control;
    };

    const auto label = [&](const wchar_t* text, int left, int top, int width, int height, HFONT font) {
        make(L"STATIC", text, SS_LEFT | SS_CENTERIMAGE, 0, left, top, width, height, font);
    };

    // ---- 顶栏：标题 + 状态指示灯（全部由 WM_PAINT 绘制，无子控件）----

    // ---- 面板 A：绝对目标响度 ----
    HWND targetEdit = make(L"EDIT", L"-16.0", ES_CENTER | ES_AUTOHSCROLL, IDC_TARGET_EDIT, 30, 102, 116, 26,
                           theme::FontMonoBig());
    SetWindowSubclass(targetEdit, TargetEditProc, 1, reinterpret_cast<DWORD_PTR>(this));
    make(L"BUTTON", L"-", BS_OWNERDRAW, IDC_TARGET_MINUS, 158, 102, 26, 26, theme::FontMono());
    make(L"BUTTON", L"+", BS_OWNERDRAW, IDC_TARGET_PLUS, 186, 102, 26, 26, theme::FontMono());
    make(L"BUTTON", L"PRESET", BS_OWNERDRAW, IDC_TARGET_PRESET, 220, 102, 112, 26, theme::FontSmall());

    label(L"绝对基准 · ↑↓/滚轮微调（Ctrl 0.1 / Shift 5）", 348, 104, 330, 22, theme::FontSmall());
    make(L"BUTTON", L"自动均衡", BS_OWNERDRAW, IDC_AUTO, 684, 101, 130, 28, theme::FontUi());
    make(L"BUTTON", L"测试模式", BS_OWNERDRAW, IDC_TESTMODE, 826, 101, 140, 28, theme::FontUi());

    // ---- 面板 B：增益 / 平滑参数 ----
    label(L"最大增益 dB", 26, 184, 90, 20, theme::FontSmall());
    make(L"EDIT", L"", ES_RIGHT | ES_AUTOHSCROLL, IDC_MAXGAIN, 120, 182, 62, 24, theme::FontMono());

    label(L"最大衰减 dB", 206, 184, 90, 20, theme::FontSmall());
    make(L"EDIT", L"", ES_RIGHT | ES_AUTOHSCROLL, IDC_MINGAIN, 300, 182, 62, 24, theme::FontMono());

    label(L"ATTACK ms", 372, 184, 90, 20, theme::FontSmall());
    make(L"EDIT", L"", ES_RIGHT | ES_AUTOHSCROLL, IDC_ATTACK, 466, 182, 62, 24, theme::FontMono());

    label(L"RELEASE ms", 536, 184, 90, 20, theme::FontSmall());
    make(L"EDIT", L"", ES_RIGHT | ES_AUTOHSCROLL, IDC_RELEASE, 630, 182, 62, 24, theme::FontMono());

    label(L"响度校准 dB", 702, 184, 90, 20, theme::FontSmall());
    make(L"EDIT", L"", ES_RIGHT | ES_AUTOHSCROLL, IDC_CALIB, 796, 182, 62, 24, theme::FontMono());

    label(L"调整速度", 26, 216, 64, 20, theme::FontSmall());
    HWND rate = make(kFaderClass, L"", WS_TABSTOP, IDC_RATE, 96, 206, 300, 36, nullptr);
    SendMessageW(rate, TBM_SETRANGE, TRUE, MAKELPARAM(0, 100));
    make(L"STATIC", L"", SS_LEFT | SS_CENTERIMAGE, IDC_RATEVAL, 404, 216, 150, 20, theme::FontMono());

    label(L"灵敏度", 26, 260, 64, 20, theme::FontSmall());
    HWND sens = make(kFaderClass, L"", WS_TABSTOP, IDC_SENS, 96, 250, 300, 36, nullptr);
    SendMessageW(sens, TBM_SETRANGE, TRUE, MAKELPARAM(0, 100));
    make(L"STATIC", L"", SS_LEFT | SS_CENTERIMAGE, IDC_SENSVAL, 404, 260, 150, 20, theme::FontMono());

    label(L"调整速度 = 每秒允许的最大 dB 变化\r\n灵敏度 = 响度统计窗口（越大响应越快）", 560, 210, 410, 62,
          theme::FontSmall());

    // ---- 面板 C：操作 ----
    make(L"BUTTON", L"暂停自动均衡", BS_OWNERDRAW, IDC_PAUSE, 26, 318, 150, 28, theme::FontUi());
    make(L"BUTTON", L"恢复所有应用原始音量", BS_OWNERDRAW, IDC_RESTORE, 190, 318, 200, 28, theme::FontUi());
    make(L"BUTTON", L"恢复自动接管", BS_OWNERDRAW, IDC_RESUME, 404, 318, 180, 28, theme::FontUi());
    label(L"手动拖动应用音量 → 该应用自动交出控制权", 600, 322, 370, 20, theme::FontSmall());

    // ---- 面板 D：会话列表 ----
    HWND list = make(L"SysListView32", L"", LVS_REPORT | LVS_SINGLESEL | LVS_SHOWSELALWAYS, IDC_LIST, 26, 392,
                     948, 268, theme::FontUi());
    ListView_SetExtendedListViewStyle(list, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER);
    SetWindowTheme(list, L"", L"");
    ListView_SetBkColor(list, theme::kWell);
    ListView_SetTextBkColor(list, theme::kWell);
    ListView_SetTextColor(list, theme::kCream);

    struct Column
    {
        const wchar_t* text;
        int width;
    };
    const Column columns[] = {
        {L"应用 / SOURCE", 208}, {L"电平", 110},  {L"音量", 74},  {L"估算响度 LUFS", 118},
        {L"目标", 82},           {L"自动增益", 100}, {L"理论调整", 92}, {L"状态", 104},
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

    HWND header = reinterpret_cast<HWND>(SendMessageW(list, LVM_GETHEADER, 0, 0));
    if (header)
    {
        SendMessageW(header, WM_SETFONT, reinterpret_cast<WPARAM>(theme::FontUi()), TRUE);
        SetWindowTheme(header, L"", L"");
        SetWindowSubclass(header, ListHeaderProc, 1, 0);
    }

    // ---- 底部状态条 ----
    make(L"STATIC", L"", SS_LEFT | SS_CENTERIMAGE | SS_ENDELLIPSIS, IDC_STATUS, 24, 674, 960, 18,
         theme::FontSmall());
}

void MainWindow::LoadSettingsToControls()
{
    SetWindowTextW(Control(IDC_TARGET_EDIT), FormatW(L"%.1f", settings_.targetLufs).c_str());
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
    InvalidateRect(Control(IDC_AUTO), nullptr, TRUE);
    InvalidateRect(Control(IDC_TESTMODE), nullptr, TRUE);
}

void MainWindow::CollectSettingsAndApply(bool saveToDisk)
{
    settings_.autoEnabled = SendMessageW(Control(IDC_AUTO), BM_GETCHECK, 0, 0) == BST_CHECKED;
    settings_.testMode = SendMessageW(Control(IDC_TESTMODE), BM_GETCHECK, 0, 0) == BST_CHECKED;
    settings_.maxGainDb = Clamp(ParseNumber(GetText(Control(IDC_MAXGAIN)), settings_.maxGainDb), 0.0, 30.0);
    settings_.minGainDb =
        Clamp(ParseNumber(GetText(Control(IDC_MINGAIN)), settings_.minGainDb), -40.0, 0.0);
    settings_.attackMs = Clamp(ParseNumber(GetText(Control(IDC_ATTACK)), settings_.attackMs), 50.0, 10000.0);
    settings_.releaseMs =
        Clamp(ParseNumber(GetText(Control(IDC_RELEASE)), settings_.releaseMs), 50.0, 10000.0);
    settings_.calibrationDb =
        Clamp(ParseNumber(GetText(Control(IDC_CALIB)), settings_.calibrationDb), -40.0, 6.0);
    settings_.sensitivity = static_cast<double>(SendMessageW(Control(IDC_SENS), TBM_GETPOS, 0, 0));
    settings_.rateDbPerSec =
        SpeedToRateDbPerSec(static_cast<double>(SendMessageW(Control(IDC_RATE), TBM_GETPOS, 0, 0)));

    if (settings_.minGainDb > settings_.maxGainDb)
        settings_.minGainDb = settings_.maxGainDb;

    engine_.ApplySettings(settings_);
    if (saveToDisk)
        SettingsManager::Save(settings_);

    UpdateDynamicLabels();
    UpdateTrayTooltip();
    InvalidateRect(hwnd_, nullptr, FALSE);
}

void MainWindow::UpdateDynamicLabels()
{
    SetWindowTextW(Control(IDC_RATEVAL), FormatW(L"%.1f dB/s", settings_.rateDbPerSec).c_str());
    SetWindowTextW(Control(IDC_SENSVAL),
                   FormatW(L"%.0f ms", SensitivityToWindowMs(settings_.sensitivity)).c_str());
    SetWindowTextW(Control(IDC_PAUSE), engine_.IsPaused() ? L"继续自动均衡" : L"暂停自动均衡");
}

void MainWindow::ApplyTarget(double value, bool saveToDisk)
{
    // 允许 -60 ~ 0 dB 的任意值，并按 0.1 dB 取整，保证显示与实际值一致
    const double clamped = Clamp(value, kTargetLufsMin, kTargetLufsMax);
    settings_.targetLufs = std::round(clamped * 10.0) / 10.0;
    SetWindowTextW(Control(IDC_TARGET_EDIT), FormatW(L"%.1f", settings_.targetLufs).c_str());
    engine_.ApplySettings(settings_);
    if (saveToDisk)
        SettingsManager::Save(settings_);
    InvalidateRect(hwnd_, nullptr, FALSE);
}

void MainWindow::NudgeTarget(double delta)
{
    ApplyTarget(settings_.targetLufs + delta, true);
}

void MainWindow::CommitTargetEdit()
{
    ApplyTarget(ParseNumber(GetText(Control(IDC_TARGET_EDIT)), settings_.targetLufs), true);
}

LRESULT CALLBACK MainWindow::TargetEditProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam,
                                            UINT_PTR subclassId, DWORD_PTR refData)
{
    UNREFERENCED_PARAMETER(subclassId);
    auto* self = reinterpret_cast<MainWindow*>(refData);
    if (!self)
        return DefSubclassProc(hwnd, message, wParam, lParam);

    const auto nudge = [self, hwnd](double delta) {
        self->NudgeTarget(delta);
        SendMessageW(hwnd, EM_SETSEL, 0, -1); // 选中全部，便于直接覆盖输入
    };

    if (message == WM_KEYDOWN)
    {
        switch (wParam)
        {
        case VK_UP:
            nudge(TargetStep());
            return 0;
        case VK_DOWN:
            nudge(-TargetStep());
            return 0;
        case VK_PRIOR:
            nudge(5.0);
            return 0;
        case VK_NEXT:
            nudge(-5.0);
            return 0;
        case VK_RETURN:
            self->CommitTargetEdit();
            SendMessageW(hwnd, EM_SETSEL, 0, -1);
            return 0;
        case VK_ESCAPE:
            SetWindowTextW(hwnd, FormatW(L"%.1f", self->settings_.targetLufs).c_str());
            SendMessageW(hwnd, EM_SETSEL, 0, -1);
            return 0;
        default:
            break;
        }
    }
    else if (message == WM_MOUSEWHEEL)
    {
        const short wheelDelta = GET_WHEEL_DELTA_WPARAM(wParam);
        if (wheelDelta != 0)
            nudge(wheelDelta > 0 ? TargetStep() : -TargetStep());
        return 0;
    }

    return DefSubclassProc(hwnd, message, wParam, lParam);
}

void MainWindow::ShowTargetPresetMenu()
{
    int count = 0;
    const LoudnessPreset* presets = LoudnessPresets(count);

    HMENU menu = CreatePopupMenu();
    if (!menu)
        return;

    for (int i = 0; i < count; ++i)
        AppendMenuW(menu, MF_STRING, IDM_PRESET_BASE + i, presets[i].label);

    RECT button = {};
    GetWindowRect(Control(IDC_TARGET_PRESET), &button);
    SetForegroundWindow(hwnd_);
    TrackPopupMenu(menu, TPM_LEFTALIGN | TPM_TOPALIGN, button.left, button.bottom, 0, hwnd_, nullptr);
    PostMessageW(hwnd_, WM_NULL, 0, 0);
    DestroyMenu(menu);
}

// ---------------------------------------------------------------------------
// 事件
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
    if (id >= IDM_PRESET_BASE)
    {
        int count = 0;
        const LoudnessPreset* presets = LoudnessPresets(count);
        const int index = id - IDM_PRESET_BASE;
        if (index >= 0 && index < count)
            ApplyTarget(presets[index].value, true);
        return;
    }

    switch (id)
    {
    case IDC_TARGET_EDIT:
        if (code == EN_KILLFOCUS)
            CommitTargetEdit();
        break;

    case IDC_TARGET_MINUS:
        if (code == BN_CLICKED)
            NudgeTarget(-TargetStep());
        break;

    case IDC_TARGET_PLUS:
        if (code == BN_CLICKED)
            NudgeTarget(TargetStep());
        break;

    case IDC_TARGET_PRESET:
        if (code == BN_CLICKED)
            ShowTargetPresetMenu();
        break;

    case IDC_AUTO:
    case IDC_TESTMODE:
    {
        HWND button = Control(id);
        const LRESULT checked = SendMessageW(button, BM_GETCHECK, 0, 0);
        SendMessageW(button, BM_SETCHECK, checked == BST_CHECKED ? BST_UNCHECKED : BST_CHECKED, 0);
        InvalidateRect(button, nullptr, TRUE);
        CollectSettingsAndApply(true);
        break;
    }

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
        InvalidateRect(hwnd_, nullptr, FALSE);
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

void MainWindow::OnDrawItem(const DRAWITEMSTRUCT& item)
{
    if (item.CtlType != ODT_BUTTON || item.itemAction == ODA_FOCUS)
        return;

    wchar_t caption[128] = {};
    GetWindowTextW(item.hwndItem, caption, 128);

    if (item.CtlID == IDC_AUTO || item.CtlID == IDC_TESTMODE)
    {
        const bool on = SendMessageW(item.hwndItem, BM_GETCHECK, 0, 0) == BST_CHECKED;
        const COLORREF color = (item.CtlID == IDC_TESTMODE) ? theme::kTeal : theme::kAmber;
        DrawLedToggle(item.hDC, item.rcItem, caption, on, color);
        return;
    }

    const bool pressed = (item.itemState & ODS_SELECTED) != 0;
    const bool accent = (item.CtlID == IDC_RESUME);
    DrawConsoleButton(item.hDC, item.rcItem, caption, pressed, accent);
}

// ---------------------------------------------------------------------------
// 自绘背景 / 面板
// ---------------------------------------------------------------------------
void MainWindow::OnPaint()
{
    PAINTSTRUCT ps = {};
    HDC dc = BeginPaint(hwnd_, &ps);

    RECT client = {};
    GetClientRect(hwnd_, &client);

    HDC memory = CreateCompatibleDC(dc);
    HBITMAP bitmap = CreateCompatibleBitmap(dc, client.right, client.bottom);
    HGDIOBJ oldBitmap = SelectObject(memory, bitmap);

    PaintConsole(memory, client);

    BitBlt(dc, 0, 0, client.right, client.bottom, memory, 0, 0, SRCCOPY);

    SelectObject(memory, oldBitmap);
    DeleteObject(bitmap);
    DeleteDC(memory);

    EndPaint(hwnd_, &ps);
}

void MainWindow::PaintConsole(HDC dc, const RECT& client)
{
    // ---- 背景：深空渐变 + 星点 ----
    theme::FillVerticalGradient(dc, client, theme::kSpaceTop, theme::kSpaceBottom);
    PaintStarField(dc, client);

    // ---- 顶栏 ----
    const RECT header = DRect(0, kHeaderTop, kClientWidth, kHeaderBottom);
    theme::FillVerticalGradient(dc, header, RGB(32, 38, 48), RGB(14, 17, 23));

    RECT accentLine = DRect(0, 0, kClientWidth, 2);
    theme::FillSolid(dc, accentLine, theme::kAmberDeep);
    RECT accentGlow = DRect(0, 2, kClientWidth, 3);
    theme::FillSolid(dc, accentGlow, RGB(46, 37, 20));
    RECT headerBottom = DRect(0, kHeaderBottom - 1, kClientWidth, kHeaderBottom);
    theme::FillSolid(dc, headerBottom, RGB(5, 7, 10));

    HGDIOBJ oldFont = SelectObject(dc, theme::FontTitle());
    theme::DrawTextSpaced(dc, L"LOUDNORM", DRect(28, 10, 460, 38), theme::kCream, D(4),
                          DT_LEFT | DT_VCENTER);

    SelectObject(dc, theme::FontSmall());
    theme::DrawTextSpaced(dc, L"ABSOLUTE LOUDNESS NORMALIZER  ·  绝对响度自动均衡", DRect(30, 34, 620, 54),
                          theme::kAmberDim, D(1), DT_LEFT | DT_VCENTER);

    // 顶栏状态灯
    const bool paused = engine_.IsPaused();
    struct HeaderLed
    {
        const wchar_t* label;
        int x;
        bool on;
        COLORREF color;
    };
    const bool agcOn = settings_.autoEnabled && !paused;
    const HeaderLed leds[] = {
        {L"AGC", 700, agcOn, theme::kAmber},
        {L"TEST", 800, settings_.testMode, theme::kTeal},
        {L"SYS", 900, engine_.IsRunning(), theme::kGreen},
    };
    for (const auto& led : leds)
    {
        theme::DrawLed(dc, D(led.x), D(22), D(5), led.color, led.on);
        RECT label = DRect(led.x - 28, 32, led.x + 28, 50);
        theme::DrawTextSpaced(dc, led.label, label, led.on ? theme::kCream : theme::kDim, D(1),
                              DT_CENTER | DT_VCENTER);
    }
    SelectObject(dc, oldFont);

    // ---- 面板标题工具 ----
    const auto sectionHeader = [&](int top, const wchar_t* title, COLORREF ledColor) {
        theme::DrawLed(dc, D(26), D(top + 13), D(3), ledColor, true);
        SelectObject(dc, theme::FontSmall());
        theme::DrawTextSpaced(dc, title, DRect(40, top + 4, 980, top + 24), theme::kAmberDim, D(1),
                              DT_LEFT | DT_VCENTER);
    };

    // ---- 面板 A ----
    const RECT plateA = DRect(12, kPlateATop, 988, kPlateABottom);
    theme::DrawPlate(dc, plateA);
    sectionHeader(kPlateATop, L"绝对目标响度  /  ABSOLUTE TARGET REFERENCE  (LUFS)", theme::kAmber);

    // ---- 面板 B ----
    const RECT plateB = DRect(12, kPlateBTop, 988, kPlateBBottom);
    theme::DrawPlate(dc, plateB);
    sectionHeader(kPlateBTop, L"增益与平滑  /  GAIN · ATTACK · RELEASE · SLEW", theme::kAmber);

    // ---- 面板 C ----
    const RECT plateC = DRect(12, kPlateCTop, 988, kPlateCBottom);
    theme::DrawPlate(dc, plateC);

    // ---- 面板 D（会话）----
    const RECT plateD = DRect(12, kPlateDTop, 988, kPlateDBottom);
    theme::DrawPlate(dc, plateD);
    sectionHeader(kPlateDTop, L"当前音频会话  /  ACTIVE SESSIONS", theme::kGreen);

    RECT listFrame = DRect(23, 389, 977, 663);
    theme::DrawWell(dc, listFrame);

    // ---- 状态条 ----
    const RECT statusPlate = DRect(12, kStatusTop, 988, kStatusBottom);
    theme::DrawPlate(dc, statusPlate);
    theme::DrawLed(dc, D(26), D(683), D(3), engine_.IsPaused() ? theme::kDim : theme::kAmber,
                   !engine_.IsPaused());

    // ---- 数值输入框的内凹显示窗 ----
    for (const auto& spec : kEditSpecs)
    {
        RECT well = DRect(spec.left - 4, spec.top - 4, spec.right + 4, spec.bottom + 4);
        theme::DrawWell(dc, well);
    }

    // 面板之间的细缝高光
    RECT divider = DRect(12, kPlateBBottom + 2, 988, kPlateBBottom + 3);
    theme::FillSolid(dc, divider, RGB(34, 40, 50));
}

// ---------------------------------------------------------------------------
// 会话列表
// ---------------------------------------------------------------------------
void MainWindow::UpdateList()
{
    HWND list = Control(IDC_LIST);
    if (!list)
        return;

    const std::vector<AppSnapshot> snapshots = engine_.Snapshots();
    lastSnapshots_ = snapshots;

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
        cells.push_back(L"");
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
        {
            if (column == kColumnLevel)
                continue;
            ListView_SetItemText(list, row, column, const_cast<wchar_t*>(cells[column].c_str()));
        }
    }

    if (desired > 0)
        ListView_RedrawItems(list, 0, desired - 1);
}

LRESULT MainWindow::OnListCustomDraw(const NMLVCUSTOMDRAW* customDraw)
{
    auto* draw = const_cast<NMLVCUSTOMDRAW*>(customDraw);

    switch (draw->nmcd.dwDrawStage)
    {
    case CDDS_PREPAINT:
    {
        RECT client = {};
        GetClientRect(draw->nmcd.hdr.hwndFrom, &client);
        FillRect(draw->nmcd.hdc, &client, theme::BrushWell());
        return CDRF_NOTIFYITEMDRAW;
    }

    case CDDS_ITEMPREPAINT:
    {
        const int row = static_cast<int>(draw->nmcd.dwItemSpec);
        const bool selected = (draw->nmcd.uItemState & CDIS_SELECTED) != 0;
        draw->clrTextBk = selected ? RGB(52, 40, 20) : ((row % 2) ? theme::kRowB : theme::kRowA);
        draw->clrText = theme::kCream;
        return CDRF_NOTIFYSUBITEMDRAW;
    }

    case CDDS_ITEMPREPAINT | CDDS_SUBITEM:
    {
        const int row = static_cast<int>(draw->nmcd.dwItemSpec);
        const int column = draw->iSubItem;
        const bool selected = (draw->nmcd.uItemState & CDIS_SELECTED) != 0;
        const bool inRange = row >= 0 && row < static_cast<int>(lastSnapshots_.size());

        if (column == kColumnLevel)
        {
            RECT cell = {};
            ListView_GetSubitemRect(draw->nmcd.hdr.hwndFrom, row, kColumnLevel, LVIR_BOUNDS, &cell);
            FillRect(draw->nmcd.hdc, &cell, selected ? theme::BrushRowA() : ((row % 2) ? theme::BrushRowB() : theme::BrushRowA()));

            if (inRange)
            {
                const AppSnapshot& snapshot = lastSnapshots_[row];
                const double ratio = snapshot.playing ? Clamp((snapshot.peakDbfs + 60.0) / 60.0, 0.0, 1.0) : 0.0;
                RECT bar = cell;
                InflateRect(&bar, -8, -8);
                if (bar.right > bar.left && bar.bottom > bar.top)
                    theme::DrawLedBar(draw->nmcd.hdc, bar, ratio, 16);
            }
            return CDRF_SKIPDEFAULT;
        }

        COLORREF color = theme::kDim;
        switch (column)
        {
        case 0:
            color = theme::kCream;
            break;
        case 2:
            color = theme::kDim;
            break;
        case 3:
            color = inRange ? theme::kAmber : theme::kDim;
            break;
        case 4:
            color = theme::kDim;
            break;
        case 5:
        {
            const double gain = inRange ? lastSnapshots_[row].appliedGainDb : 0.0;
            color = (gain > 0.2) ? theme::kGreen : ((gain < -0.2) ? theme::kAmber : theme::kDim);
            break;
        }
        case 6:
            color = theme::Blend(theme::kDim, theme::kTeal, 0.45);
            break;
        case 7:
        {
            AppState state = inRange ? lastSnapshots_[row].state : AppState::Disabled;
            switch (state)
            {
            case AppState::Adjusting: color = theme::kAmber; break;
            case AppState::Stable: color = theme::kGreen; break;
            case AppState::Capped: color = theme::kRed; break;
            case AppState::Manual: color = theme::kTeal; break;
            case AppState::TestMode: color = theme::kTeal; break;
            case AppState::Warming: color = theme::kAmberDim; break;
            default: color = theme::kDim; break;
            }
            break;
        }
        default:
            break;
        }

        draw->clrText = color;
        return CDRF_DODEFAULT;
    }

    default:
        break;
    }

    return CDRF_DODEFAULT;
}

// ---------------------------------------------------------------------------
// 托盘
// ---------------------------------------------------------------------------
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
    engine_.Stop();
    tray_.Remove();

    if (hwnd_)
        DestroyWindow(hwnd_);
}

} // namespace ln
