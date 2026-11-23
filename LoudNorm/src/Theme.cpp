// Theme.cpp
#include "Theme.h"

#pragma comment(lib, "msimg32.lib")

namespace ln {
namespace theme {

namespace {

HFONT g_ui = nullptr;
HFONT g_small = nullptr;
HFONT g_mono = nullptr;
HFONT g_monoBig = nullptr;
HFONT g_title = nullptr;

HBRUSH g_panel = nullptr;
HBRUSH g_well = nullptr;
HBRUSH g_rowA = nullptr;
HBRUSH g_rowB = nullptr;
HBRUSH g_header = nullptr;

HFONT MakeFont(int pointSize, int dpi, int weight, const wchar_t* face)
{
    return CreateFontW(-MulDiv(pointSize, dpi, 72), 0, 0, 0, weight, FALSE, FALSE, FALSE,
                       DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                       DEFAULT_PITCH | FF_DONTCARE, face);
}

} // namespace

void Create(int dpi)
{
    Destroy();

    // 中文用雅黑，数字/读数用等宽（更像仪器面板）
    g_ui = MakeFont(9, dpi, FW_NORMAL, L"Microsoft YaHei UI");
    g_small = MakeFont(8, dpi, FW_NORMAL, L"Microsoft YaHei UI");
    g_mono = MakeFont(10, dpi, FW_NORMAL, L"Consolas");
    g_monoBig = MakeFont(15, dpi, FW_BOLD, L"Consolas");
    g_title = MakeFont(14, dpi, FW_BOLD, L"Microsoft YaHei UI");

    g_panel = CreateSolidBrush(kPanel);
    g_well = CreateSolidBrush(kWell);
    g_rowA = CreateSolidBrush(kRowA);
    g_rowB = CreateSolidBrush(kRowB);
    g_header = CreateSolidBrush(kHeaderBar);
}

void Destroy()
{
    HFONT fonts[] = {g_ui, g_small, g_mono, g_monoBig, g_title};
    for (HFONT font : fonts)
    {
        if (font)
            DeleteObject(font);
    }
    g_ui = g_small = g_mono = g_monoBig = g_title = nullptr;

    HBRUSH brushes[] = {g_panel, g_well, g_rowA, g_rowB, g_header};
    for (HBRUSH brush : brushes)
    {
        if (brush)
            DeleteObject(brush);
    }
    g_panel = g_well = g_rowA = g_rowB = g_header = nullptr;
}

HFONT FontUi() { return g_ui; }
HFONT FontSmall() { return g_small; }
HFONT FontMono() { return g_mono; }
HFONT FontMonoBig() { return g_monoBig; }
HFONT FontTitle() { return g_title; }

HBRUSH BrushPanel() { return g_panel; }
HBRUSH BrushWell() { return g_well; }
HBRUSH BrushRowA() { return g_rowA; }
HBRUSH BrushRowB() { return g_rowB; }
HBRUSH BrushHeader() { return g_header; }

COLORREF Blend(COLORREF a, COLORREF b, double t)
{
    t = Clamp(t, 0.0, 1.0);
    return RGB(static_cast<int>(GetRValue(a) * (1.0 - t) + GetRValue(b) * t),
               static_cast<int>(GetGValue(a) * (1.0 - t) + GetGValue(b) * t),
               static_cast<int>(GetBValue(a) * (1.0 - t) + GetBValue(b) * t));
}

void FillSolid(HDC dc, const RECT& rc, COLORREF color)
{
    HBRUSH brush = CreateSolidBrush(color);
    FillRect(dc, &rc, brush);
    DeleteObject(brush);
}

void FillVerticalGradient(HDC dc, const RECT& rc, COLORREF top, COLORREF bottom)
{
    TRIVERTEX vertex[2] = {};
    vertex[0].x = rc.left;
    vertex[0].y = rc.top;
    vertex[0].Red = static_cast<COLOR16>(GetRValue(top) << 8);
    vertex[0].Green = static_cast<COLOR16>(GetGValue(top) << 8);
    vertex[0].Blue = static_cast<COLOR16>(GetBValue(top) << 8);
    vertex[0].Alpha = 0;

    vertex[1].x = rc.right;
    vertex[1].y = rc.bottom;
    vertex[1].Red = static_cast<COLOR16>(GetRValue(bottom) << 8);
    vertex[1].Green = static_cast<COLOR16>(GetGValue(bottom) << 8);
    vertex[1].Blue = static_cast<COLOR16>(GetBValue(bottom) << 8);
    vertex[1].Alpha = 0;

    GRADIENT_RECT mesh = {0, 1};
    GradientFill(dc, vertex, 2, &mesh, 1, GRADIENT_FILL_RECT_V);
}

void DrawOutline(HDC dc, const RECT& rc, COLORREF color)
{
    HBRUSH brush = CreateSolidBrush(color);
    FrameRect(dc, &rc, brush);
    DeleteObject(brush);
}

// 凸起面板：填充 + 上沿高光 + 下沿阴影 + 外描边
void DrawPlate(HDC dc, const RECT& rc)
{
    FillSolid(dc, rc, kPanel);

    RECT top = {rc.left + 1, rc.top + 1, rc.right - 1, rc.top + 2};
    FillSolid(dc, top, kPanelHi);

    RECT bottom = {rc.left + 1, rc.bottom - 2, rc.right - 1, rc.bottom - 1};
    FillSolid(dc, bottom, kPanelLo);

    RECT left = {rc.left + 1, rc.top + 1, rc.left + 2, rc.bottom - 1};
    FillSolid(dc, left, Blend(kPanel, kPanelHi, 0.35));

    RECT right = {rc.right - 2, rc.top + 1, rc.right - 1, rc.bottom - 1};
    FillSolid(dc, right, Blend(kPanel, kPanelLo, 0.45));

    DrawOutline(dc, rc, RGB(58, 67, 80));
}

// 内凹显示窗
void DrawWell(HDC dc, const RECT& rc)
{
    FillSolid(dc, rc, kWell);

    RECT top = {rc.left + 1, rc.top + 1, rc.right - 1, rc.top + 2};
    FillSolid(dc, top, RGB(4, 5, 7));

    RECT bottom = {rc.left + 1, rc.bottom - 2, rc.right - 1, rc.bottom - 1};
    FillSolid(dc, bottom, kWellHi);

    RECT left = {rc.left + 1, rc.top + 1, rc.left + 2, rc.bottom - 1};
    FillSolid(dc, left, RGB(4, 5, 7));

    RECT right = {rc.right - 2, rc.top + 1, rc.right - 1, rc.bottom - 1};
    FillSolid(dc, right, Blend(kWell, kWellHi, 0.6));

    DrawOutline(dc, rc, RGB(2, 3, 4));
}

void DrawTextSimple(HDC dc, const std::wstring& text, RECT rc, COLORREF color, UINT flags)
{
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, color);
    DrawTextW(dc, text.c_str(), static_cast<int>(text.size()), &rc, flags);
}

void DrawTextSpaced(HDC dc, const std::wstring& text, RECT rc, COLORREF color, int spacing, UINT flags)
{
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, color);

    if (spacing <= 0 || text.empty())
    {
        DrawTextW(dc, text.c_str(), static_cast<int>(text.size()), &rc, flags);
        return;
    }

    int total = 0;
    for (wchar_t ch : text)
    {
        SIZE size = {};
        GetTextExtentPoint32W(dc, &ch, 1, &size);
        total += size.cx + spacing;
    }
    total -= spacing;

    int x = rc.left;
    if (flags & DT_CENTER)
        x = rc.left + ((rc.right - rc.left) - total) / 2;

    int y = rc.top;
    if (flags & DT_VCENTER)
    {
        TEXTMETRICW metrics = {};
        GetTextMetricsW(dc, &metrics);
        y = rc.top + ((rc.bottom - rc.top) - metrics.tmHeight) / 2;
    }

    for (wchar_t ch : text)
    {
        SIZE size = {};
        GetTextExtentPoint32W(dc, &ch, 1, &size);
        TextOutW(dc, x, y, &ch, 1);
        x += size.cx + spacing;
    }
}

void DrawLed(HDC dc, int cx, int cy, int radius, COLORREF color, bool on)
{
    HBRUSH glowBrush = CreateSolidBrush(on ? Blend(color, RGB(0, 0, 0), 0.62) : RGB(24, 28, 35));
    HBRUSH coreBrush = CreateSolidBrush(on ? color : RGB(46, 52, 61));
    HPEN nullPen = static_cast<HPEN>(GetStockObject(NULL_PEN));

    HGDIOBJ oldBrush = SelectObject(dc, glowBrush);
    HGDIOBJ oldPen = SelectObject(dc, nullPen);

    Ellipse(dc, cx - radius - 2, cy - radius - 2, cx + radius + 3, cy + radius + 3);

    SelectObject(dc, coreBrush);
    Ellipse(dc, cx - radius, cy - radius, cx + radius + 1, cy + radius + 1);

    SelectObject(dc, oldBrush);
    SelectObject(dc, oldPen);
    DeleteObject(glowBrush);
    DeleteObject(coreBrush);
}

void DrawLedBar(HDC dc, const RECT& rc, double ratio, int segments)
{
    if (segments < 2)
        segments = 2;

    FillSolid(dc, rc, kWell);

    const int gap = 2;
    const int width = rc.right - rc.left;
    const int segWidth = std::max(2, (width - gap * (segments - 1)) / segments);
    const int lit = static_cast<int>(std::lround(Clamp(ratio, 0.0, 1.0) * segments));

    for (int i = 0; i < segments; ++i)
    {
        const double position = static_cast<double>(i + 1) / segments;
        COLORREF color = kGreen;
        if (position > 0.86)
            color = kRed;
        else if (position > 0.62)
            color = kAmber;

        RECT seg = {rc.left + i * (segWidth + gap), rc.top, rc.left + i * (segWidth + gap) + segWidth,
                    rc.bottom};

        if (seg.right > rc.right)
            seg.right = rc.right;

        FillSolid(dc, seg, i < lit ? color : RGB(24, 28, 35));
    }
}

} // namespace theme
} // namespace ln
