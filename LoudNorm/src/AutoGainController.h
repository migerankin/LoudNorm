// AutoGainController.h - 由“估算响度 vs 绝对目标响度”计算目标增益，
// 并负责 Attack / Release / 平滑 / 速率限制 / 迟滞(死区) / 增益上下限。
#pragma once

#include "AppSession.h"
#include "Common.h"
#include "Settings.h"

namespace ln {

struct GainDecision
{
    bool apply = false;              // 是否需要写入音量
    double requestedGainDb = 0.0;    // 本轮希望达到的增益
    float appliedScalar = 1.0f;      // 对应需要写入的会话音量标量
    bool capped = false;             // 是否已被音量上限/增益上限截断
};

class AutoGainController
{
public:
    // 每个应用独立执行一次。mayApply=false 时只计算不写入（测试模式 / 暂停 / 关闭）。
    GainDecision Step(AppSession& app, const Settings& settings, double dtSeconds, bool mayApply);

private:
    void RecordSample(AppSession& app, double dtSeconds);
    void UpdateResponseSlope(AppSession& app);
};

} // namespace ln
