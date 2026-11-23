// Theme.h - 录音棚调音台 / 太空复古风格：调色板、字体、绘制工具
#pragma once

#include "Common.h"

namespace ln {
namespace theme {

// ---- 调色板 ---------------------------------------------------------------
constexpr COLORREF kSpaceTop = RGB(9, 11, 16);      // 背景渐变（上）
constexpr COLORREF kSpaceBottom = RGB(21, 26, 35);  // 背景渐变（下）
constexpr COLORREF kPanel = RGB(26, 31, 40);        // 面板底板
constexpr COLORREF kPanelHi = RGB(52, 61, 74);      // 面板上沿高光
constexpr COLORREF kPanelLo = RGB(6, 8, 11);        // 面板下沿阴影
constexpr COLORREF kWell = RGB(11, 14, 19);         // 内凹显示窗
constexpr COLORREF kWellHi = RGB(38, 45, 56);
constexpr COLORREF kRowA = RGB(21, 25, 32);
constexpr COLORREF kRowB = RGB(17, 21, 27);
constexpr COLORREF kHeaderBar = RGB(33, 39, 49);
constexpr COLORREF kAmber = RGB(255, 178, 64);      // 主强调色（电子管琥珀）
constexpr COLORREF kAmberDim = RGB(152, 100, 33);
constexpr COLORREF kAmberDeep = RGB(92, 58, 16);
constexpr COLORREF kCream = RGB(238, 231, 214);     // 丝印白
constexpr COLORREF kDim = RGB(136, 148, 165);       // 次要文字
constexpr COLORREF kTeal = RGB(82, 209, 199);       // 太空青
constexpr COLORREF kGreen = RGB(126, 216, 143);
constexpr COLORREF kRed = RGB(228, 88, 76);
constexpr COLORREF kBrass = RGB(178, 141, 80);

void Create(int dpi);
void Destroy();

HFONT FontUi();
HFONT FontSmall();
HFONT FontMono();
HFONT FontMonoBig();
HFONT FontTitle();

HBRUSH BrushPanel();
HBRUSH BrushWell();
HBRUSH BrushRowA();
HBRUSH BrushRowB();
HBRUSH BrushHeader();

void FillSolid(HDC dc, const RECT& rc, COLORREF color);
void FillVerticalGradient(HDC dc, const RECT& rc, COLORREF top, COLORREF bottom);
void DrawPlate(HDC dc, const RECT& rc);
void DrawWell(HDC dc, const RECT& rc);
void DrawOutline(HDC dc, const RECT& rc, COLORREF color);

// 字间距文本（模仿面板丝印 / 刻字），flags 支持 DT_CENTER / DT_VCENTER
void DrawTextSpaced(HDC dc, const std::wstring& text, RECT rc, COLORREF color, int spacing, UINT flags);
void DrawTextSimple(HDC dc, const std::wstring& text, RECT rc, COLORREF color, UINT flags);

void DrawLed(HDC dc, int cx, int cy, int radius, COLORREF color, bool on);
void DrawLedBar(HDC dc, const RECT& rc, double ratio, int segments);

COLORREF Blend(COLORREF a, COLORREF b, double t);

} // namespace theme
} // namespace ln
