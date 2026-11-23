// VolumeController.h - 通过 ISimpleAudioVolume 修改“单个应用”的音量（不触碰系统主音量）
#pragma once

#include "Common.h"

#include <audiopolicy.h>
#include <endpointvolume.h>

namespace ln {

class VolumeController
{
public:
    static bool GetVolume(ISimpleAudioVolume* volume, float& scalar);
    static bool SetVolume(ISimpleAudioVolume* volume, float scalar);
    static bool Restore(ISimpleAudioVolume* volume, float originalScalar);

    // 由“原始音量 + 目标增益(db)”计算需要写入的会话音量标量（0..1）
    static float ScalarForGain(float originalScalar, double gainDb);

    // 由“原始音量 + 实际写入值”反算实际获得的增益（考虑 1.0 上限截断）
    static double GainOf(float originalScalar, float currentScalar);
};

} // namespace ln
