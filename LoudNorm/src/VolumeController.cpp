// VolumeController.cpp
#include "VolumeController.h"

namespace ln {

bool VolumeController::GetVolume(ISimpleAudioVolume* volume, float& scalar)
{
    if (!volume)
        return false;
    return SUCCEEDED(volume->GetMasterVolume(&scalar));
}

bool VolumeController::SetVolume(ISimpleAudioVolume* volume, float scalar)
{
    if (!volume)
        return false;
    const float clamped = static_cast<float>(Clamp(scalar, 0.0, 1.0));
    // 事件上下文传 nullptr：不需要会话音量变化通知
    return SUCCEEDED(volume->SetMasterVolume(clamped, nullptr));
}

bool VolumeController::Restore(ISimpleAudioVolume* volume, float originalScalar)
{
    return SetVolume(volume, originalScalar);
}

float VolumeController::ScalarForGain(float originalScalar, double gainDb)
{
    const double original = Clamp(originalScalar, 0.0f, 1.0f);
    if (original <= 0.0)
        return 0.0f;
    double target = original * DbToLinear(gainDb);
    // 允许轻微超过 1.0 吗？不允许：会话音量上限即 1.0
    return static_cast<float>(Clamp(target, 0.0, 1.0));
}

double VolumeController::GainOf(float originalScalar, float currentScalar)
{
    const double original = static_cast<double>(originalScalar);
    const double current = static_cast<double>(currentScalar);
    if (original <= 1e-6 || current <= 1e-6)
        return -140.0;
    return 20.0 * std::log10(current / original);
}

} // namespace ln
