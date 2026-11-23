// FaderControl.cpp - 调音台推子（自绘）
#include "FaderControl.h"

#include "Theme.h"

#include <windowsx.h>

namespace ln {
namespace {

struct FaderState
{
    int minimum = 0;
    int maximum = 100;
    int position = 50;
    bool dragging = false;
};

constexpr int kMargin = 12;

int PositionFromX(const RECT& rc, int x, const FaderState& state)
{
    const int left = rc.left + kMargin;
    const int right = rc.right - kMargin;
    const int width = std::max(1, right - left);
    const double t = Clamp(static_cast<double>(x - left) / static_cast<double>(width), 0.0, 1.0);
    const int span = std::max(1, state.maximum - state.minimum);
    return state.minimum + static_cast<int>(std::lround(t * span));
}

void NotifyParent(HWND hwnd, const FaderState& state)
{
    SendMessageW(GetParent(hwnd), WM_HSCROLL,
                 MAKEWPARAM(SB_THUMBPOSITION, static_cast<WORD>(state.position)),
                 reinterpret_cast<LPARAM>(hwnd));
}

void PaintFader(HWND hwnd, HDC dc, const FaderState& state)
{
    RECT rc = {};
    GetClientRect(hwnd, &rc);
    theme::FillSolid(dc, rc, theme::kPanel);

    const int left = rc.left + kMargin;
    const int right = rc.right - kMargin;
    const int centerY = (rc.top + rc.bottom) / 2;
    const int span = std::max(1, state.maximum - state.minimum);
    const double t = Clamp(static_cast<double>(state.position - state.minimum) / span, 0.0, 1.0);
    const int thumbX = left + static_cast<int>(std::lround(t * (right - left)));

    // 上下刻度线
    for (int i = 0; i <= 10; ++i)
    {
        const int x = left + (right - left) * i / 10;
        const bool major = (i % 5 == 0);
        RECT upper = {x, rc.top + 3, x + 1, rc.top + (major ? 10 : 7)};
        RECT lower = {x, rc.bottom - (major ? 10 : 7), x + 1, rc.bottom - 3};
        theme::FillSolid(dc, upper, major ? theme::kAmberDim : RGB(52, 61, 74));
        theme::FillSolid(dc, lower, major ? theme::kAmberDim : RGB(40, 47, 58));
    }

    // 导轨
    RECT rail = {left, centerY - 5, right, centerY + 5};
    theme::DrawWell(dc, rail);

    // 已推起部分（琥珀发光条）
    if (thumbX > left)
    {
        RECT fill = {left + 1, centerY - 4, thumbX, centerY + 4};
        theme::FillSolid(dc, fill, theme::kAmberDeep);
        RECT core = {left + 1, centerY - 1, thumbX, centerY + 1};
        theme::FillSolid(dc, core, theme::kAmber);
    }

    // 推子帽
    RECT knob = {thumbX - 9, centerY - 15, thumbX + 10, centerY + 16};
    theme::FillSolid(dc, knob, RGB(40, 47, 58));
    RECT knobTop = {knob.left + 1, knob.top + 1, knob.right - 1, knob.top + 2};
    theme::FillSolid(dc, knobTop, RGB(88, 99, 116));
    RECT knobBottom = {knob.left + 1, knob.bottom - 2, knob.right - 1, knob.bottom - 1};
    theme::FillSolid(dc, knobBottom, RGB(8, 10, 13));
    RECT mark = {knob.left + 3, centerY - 1, knob.right - 3, centerY};
    theme::FillSolid(dc, mark, state.dragging ? theme::kTeal : theme::kAmber);
    theme::DrawOutline(dc, knob, RGB(14, 17, 22));
}

LRESULT CALLBACK FaderProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam)
{
    auto* state = reinterpret_cast<FaderState*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));

    switch (message)
    {
    case WM_CREATE:
    {
        auto* created = new FaderState();
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(created));
        return 0;
    }
    case WM_DESTROY:
        delete state;
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
        return 0;
    default:
        break;
    }

    if (!state)
        return DefWindowProcW(hwnd, message, wParam, lParam);

    switch (message)
    {
    case WM_ERASEBKGND:
        return 1;

    case WM_PAINT:
    {
        PAINTSTRUCT ps = {};
        HDC dc = BeginPaint(hwnd, &ps);
        PaintFader(hwnd, dc, *state);
        EndPaint(hwnd, &ps);
        return 0;
    }

    case TBM_SETRANGE:
    {
        state->minimum = static_cast<int>(LOWORD(lParam));
        state->maximum = static_cast<int>(HIWORD(lParam));
        if (state->maximum <= state->minimum)
            state->maximum = state->minimum + 1;
        state->position = static_cast<int>(Clamp(static_cast<double>(state->position), state->minimum, state->maximum));
        if (wParam)
            InvalidateRect(hwnd, nullptr, FALSE);
        return 0;
    }

    case TBM_SETPOS:
        state->position = static_cast<int>(Clamp(static_cast<double>(lParam), state->minimum, state->maximum));
        if (wParam)
            InvalidateRect(hwnd, nullptr, FALSE);
        return 0;

    case TBM_GETPOS:
        return state->position;

    case TBM_GETRANGEMIN:
        return state->minimum;

    case TBM_GETRANGEMAX:
        return state->maximum;

    case WM_LBUTTONDOWN:
    {
        RECT rc = {};
        GetClientRect(hwnd, &rc);
        state->position = PositionFromX(rc, GET_X_LPARAM(lParam), *state);
        state->dragging = true;
        SetCapture(hwnd);
        SetFocus(hwnd);
        InvalidateRect(hwnd, nullptr, FALSE);
        NotifyParent(hwnd, *state);
        return 0;
    }

    case WM_MOUSEMOVE:
        if (state->dragging)
        {
            RECT rc = {};
            GetClientRect(hwnd, &rc);
            const int next = PositionFromX(rc, GET_X_LPARAM(lParam), *state);
            if (next != state->position)
            {
                state->position = next;
                InvalidateRect(hwnd, nullptr, FALSE);
                NotifyParent(hwnd, *state);
            }
        }
        return 0;

    case WM_LBUTTONUP:
        if (state->dragging)
        {
            state->dragging = false;
            ReleaseCapture();
            InvalidateRect(hwnd, nullptr, FALSE);
            NotifyParent(hwnd, *state);
        }
        return 0;

    case WM_MOUSEWHEEL:
    {
        const int delta = GET_WHEEL_DELTA_WPARAM(wParam) > 0 ? 2 : -2;
        const int next = static_cast<int>(Clamp(static_cast<double>(state->position + delta), state->minimum,
                                                state->maximum));
        if (next != state->position)
        {
            state->position = next;
            InvalidateRect(hwnd, nullptr, FALSE);
            NotifyParent(hwnd, *state);
        }
        return 0;
    }

    case WM_KEYDOWN:
    {
        int next = state->position;
        switch (wParam)
        {
        case VK_LEFT:
        case VK_DOWN:
            next -= 1;
            break;
        case VK_RIGHT:
        case VK_UP:
            next += 1;
            break;
        case VK_HOME:
            next = state->minimum;
            break;
        case VK_END:
            next = state->maximum;
            break;
        default:
            return DefWindowProcW(hwnd, message, wParam, lParam);
        }
        next = static_cast<int>(Clamp(static_cast<double>(next), state->minimum, state->maximum));
        if (next != state->position)
        {
            state->position = next;
            InvalidateRect(hwnd, nullptr, FALSE);
            NotifyParent(hwnd, *state);
        }
        return 0;
    }

    case WM_SETFOCUS:
    case WM_KILLFOCUS:
        InvalidateRect(hwnd, nullptr, FALSE);
        return 0;

    default:
        break;
    }

    return DefWindowProcW(hwnd, message, wParam, lParam);
}

} // namespace

bool RegisterFaderClass(HINSTANCE instance)
{
    static bool registered = false;
    if (registered)
        return true;

    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(WNDCLASSEXW);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = FaderProc;
    wc.hInstance = instance;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = nullptr;
    wc.lpszClassName = kFaderClass;

    if (!RegisterClassExW(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
        return false;

    registered = true;
    return true;
}

} // namespace ln
