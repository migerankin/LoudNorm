// FaderControl.h - 调音台风格的推子（自绘 slider），兼容 TBM_SETRANGE / TBM_GETPOS / TBM_SETPOS
#pragma once

#include "Common.h"

namespace ln {

constexpr wchar_t kFaderClass[] = L"LoudNormFader";

bool RegisterFaderClass(HINSTANCE instance);

} // namespace ln
