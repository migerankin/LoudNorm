# autolevel

Windows 上的按应用音量自动平衡工具。

游戏、YouTube 视频和 Discord 通话的母带电平各不相同，结果你整天都在拖动音量合成器的滑块。`autolevel` 会观察每个应用实际输出的声音，并持续替你移动这些滑块，让所有声音听起来一样响。

常规平衡不需要驱动、管理员权限或虚拟声卡；它用的是与音量合成器相同的 Windows Core Audio 会话 API。可选的**真实增强**使用独立的 WASAPI 端点桥接，让指定应用可以超过 100%。

## 运行

双击 **`dist\autolevel-gui.exe`**。无需安装 —— 不需要 Python、不需要管理员权限、不需要驱动。

```
┌──────────────────────────────────────────────────────────┐
│  [ 开始平衡 ]  [ 设置 ]              目标      -18.0      │
│                                        ────────●──────    │
├──────────────────────────────────────────────────────────┤
│  ☑ 自动暂停  ☐ 试运行         已降低音乐 - discord 正在播放│
├──────────────────────────────────────────────────────────┤
│  ☑ chrome.exe                                             │
│    活跃     -6.0 dB  增益  -12.0 dB   ████████████░░░░     │
│  ☑ Spotify.exe                                            │
│    已压低  -21.4 dB  增益  -20.0 dB   ███████░░░░░░░░░     │
│  ☑ discord.exe                                            │
│    活跃    -18.2 dB  增益    0.0 dB   █████████░░░░░░░     │
├──────────────────────────────────────────────────────────┤
│  正在平衡 3 个应用                                        │
└──────────────────────────────────────────────────────────┘
```

按**开始平衡**并让它一直运行。拖动目标滑块可以选择共同的电平。取消勾选某个应用就不再管它 —— 它会立即被释放并恢复原音量。应用被压低时，电平条会变成蓝色。

## 配置档

内置两个可直接用的配置档，用顶部的下拉框可以瞬间切换：

| | 游戏 | 休闲 |
| --- | --- | --- |
| `target_db` | `-14.0` —— 更响，游戏动态大 | `-20.0` —— 更安静，适合背景收听 |
| `slew_db_per_s` | `9.0` —— 反应快 | `4.0` —— 修正听不出来 |
| 视频触发时 | `duck` —— 绝不在游戏中掐断声音 | `pause` —— 放视频时音乐停下 |
| 语音门限 | `-48 dB` —— 能捕捉说话轻的队友 | `-45 dB` |
| 语音保持 | `2.0 s` —— 对话中减少断续 | `1.5 s` |

可以从**顶部下拉框**、**托盘菜单**（连窗口都不用打开）或命令行切换：

```powershell
autolevel profiles                      # 列出配置档，* 标记当前启用的
autolevel profiles --activate 游戏
autolevel profiles --save "电影之夜"     # 把当前设置存成指定名称
autolevel profiles --delete "电影之夜"
autolevel --profile 休闲 run             # 仅本次运行使用，不切换当前配置
```

### 创建自己的配置档

点配置档下拉框旁边的 **+**，随便输入一个名字即可 —— 它会把当前设置存成该名称。若名字已被占用，对话框会提示，按钮也会变成**替换**，所以不会误覆盖。

设置里的**配置档**标签页还有其余功能：**载入**、**更新**（用当前设置覆盖所选配置档）、**复制…**（复制现有配置档作为起点）、**重命名…**、**删除**，以及**用当前设置新建配置档…**。

### 修改已有配置档

**保存**只写入你的设置，不会动它来源的那个配置档 —— 否则做实验就会悄悄改掉你的预设。要把改动合并回去，请选中该配置档再按**更新**。在此之前选择器会显示 `游戏（已修改）`，保存消息里也会提醒你。

名称是自由文本 —— `raid night 2am`、`Chill - late`、`Zone 3` 都可以。唯一的规则是不能为空，且不超过 40 个字符。

### 配置档到底是什么

一份完整的设置副本。切换配置档会**替换**你当前的设置 —— 它不是叠加在上面的，也不存在第二个"真实来源"。`config.json` 永远是当前生效的设置；`profiles.json` 只是一批可供找回的快照库。

这么简单的代价是：如果你之后又改了设置，配置档就"过期"了。选择器会如实说明，而不是骗你：

```
游戏              设置与该配置档完全一致
游戏（已修改）     从该配置档开始，之后被改动过
（未保存）        这些设置与任何配置档都不匹配
```

用相同名称的*把当前设置另存为*即可把改动合并回去。

载入失败的配置档（比如手工改成了非法值）会被跳过并给出提示，而不会让程序无法启动；未知字段会被忽略，因此新版程序写的配置档在旧版里也能打开。

## 设置

**设置**，或 `Ctrl+,`。共六个标签页 —— 电平、增强、自动暂停、语音、窗口、配置档。

每一行都标出它对应的真实 `config.json` 键名，下面附一句中文说明：

```
target_db                                          [ -18.0 ]
# 所有应用都被拉向的目标电平。设得越低，留给未经真实增强桥接的应用余量越大。

autopause_voice_apps               [ discord, teams, zoom    ]
# 这些应用的语音活动会压低音乐。它们不注册媒体会话，
# 因此改用响度检测。
```

所以没有另一套只在界面里用的词汇要学，之后手工改配置文件时用的也是你已经见过的名字。

**保存**会先校验再应用，并就地报告问题 —— 把 `gate_db` 设得高于 `target_db` 会当场告诉你，而不是等运行时报错。设置持久化到 `%APPDATA%\autolevel\config.json`，重启后依然有效。**默认值**只重置字段，不保存就不写入任何内容。

目标电平以及**所有自动暂停设置**都即时生效，即使平衡正在运行 —— 视频播到一半从 duck 改成 pause，音乐会被当场释放并暂停。影响电平形状的设置（`gate_db`、`slew_db_per_s`、`attack_ms`、`release_ms`、`settle_ms`）是在循环启动时读取的。增强的端点设置同样需要重启，因为它要重建实时音频流；状态栏会说明这一点，而不是假装已经生效。

## 超过 100% 的真实增强

Windows 的按应用滑块无法超过 100%，所以真实增强走另一条音频路径：

```
选中的应用 -> 源端点回环 -> 增益 -> 峰值限幅 -> 扬声器
```

源端点必须与扬声器是**不同的渲染端点**。它可以是一个空闲的物理输出（如 HDMI/Realtek），也可以是虚拟声卡。AutoLevel 不会安装驱动。如果机器只有一个输出，请先自行安装一个虚拟音频端点再启用此功能。

1. 列出准确的端点名称：

   ```powershell
   autolevel boost
   ```

2. 打开 Windows 的按应用音量合成器，只把想增强的应用路由到源端点：

   ```powershell
   autolevel boost --open-mixer
   ```

3. 打开**设置 -> 增强**，复制源端点名称，选择输出扬声器（留空则用默认设备），设置增益并启用增强。等价的 `config.json` 是：

   ```json
   {
     "boost_enabled": true,
     "boost_source_device": "Speakers (Realtek(R) Audio)",
     "boost_output_device": "Speakers (USB Audio)",
     "boost_gain_db": 6.0,
     "boost_ceiling_db": -1.0,
     "boost_sample_rate": 48000,
     "boost_block_frames": 480
   }
   ```

4. 正常开始平衡，或为单次运行临时配置：

   ```powershell
   autolevel run --boost --boost-source "Speakers (Realtek(R) Audio)" `
     --boost-output "Speakers (USB Audio)" --boost-gain 6
   ```

在把真实应用路由过来之前，先让桥接跑一秒，确认音频流状态：

```powershell
autolevel boost --check --boost-source "Speakers (Realtek(R) Audio)" `
  --boost-output "Speakers (USB Audio)" --boost-gain 6
```

检查结果会报告处理的帧数、最高输出峰值和实际施加的增益。

`boost_gain_db` 是真正的正增益：+6 dB 约为两倍幅度。允许取值为大于 0 且不超过 +60 dB。块峰值限幅器会在必要时自动降低增益，使输出不超过 `boost_ceiling_db`；当前的压限量会显示在 CLI/GUI 状态里。路由到源端点的所有应用共用这条增强通路，用 Windows 音量合成器决定哪些应用属于其中。

## 后台运行

关闭窗口会**隐藏到托盘**，平衡继续进行。托盘图标在工作时变蓝，提示文字显示正在管理多少个应用。右键可开始/停止、开关自动暂停、开机自启，以及退出 —— 只有退出才会恢复你的原始音量并真正结束进程。

勾选**开机自动启动**后，它会在登录时直接进入托盘并已开始平衡。不需要管理员权限：只写入 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下的一个值。

```powershell
autolevel startup             # 查看是否开机启动，以及用什么命令启动
autolevel startup --enable
autolevel startup --disable
autolevel gui --minimized     # 登录时实际执行的命令
```

如果你移动或重新构建了 exe，开机启动项会变"过期" —— 窗口底部会提示，重新勾选一次即可指向新位置。

## 在另一台设备上安装

不需要 Python、不需要构建、不需要管理员权限：

1. 打开 [Releases](../../releases) 页面。
2. 从最新发布中下载 **`autolevel-gui.exe`**。
3. 运行即可。可选地勾选**开机自动启动**，让它下次登录时自动回来。

同一发布里的 `autolevel.exe` 是命令行版本；只有当你需要 `autolevel list`、`profiles` 或写脚本时才用得上。

首次运行时 Windows SmartScreen 很可能会警告，因为 exe 没有签名 —— 选择*更多信息* → *仍要运行*。代码签名需要付费证书，没有证书就无法绕过该提示。

### 设置不会在设备之间同步

每台机器各自保存 `%APPDATA%\autolevel\config.json` 和 `profiles.json`。这通常正是你想要的，因为笔记本和台式机很少需要相同的目标电平。想复制整套配置，就复制这两个文件。

开机启动项也是按机器保存的，而且存的是绝对路径 —— 所以每台设备都要重新勾选**开机自动启动**，移动 exe 后也要重新勾选。

## 发布

`dist/` 是刻意排除在 git 之外的：每个 exe 约 43 MB，每次提交构建产物都会永久撑大仓库体积。它们以 Release 附件的形式分发。

推送 `v*` 标签即可，CI 会代劳：

```powershell
git tag v0.2.0
git push origin v0.2.0
```

`.github/workflows/build.yml` 随后在 Windows runner 上跑测试、调用 `build.ps1` 打包，并把 `autolevel-gui.exe` 与 `autolevel.exe` 附加到同名 Release（已存在则只更新附件）。用 `gh workflow run` 或 Actions 页面的 **Run workflow** 手动触发时，产物只留在该次运行的 Artifacts 里，不会发版。

想先在本地验证，仍可直接构建：

```powershell
.\build.ps1
```

## 构建可执行文件

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
uv pip install --python .venv\Scripts\python.exe pyinstaller
.\build.ps1
```

产出 `dist\autolevel-gui.exe`（窗口版，约 43 MB）和 `dist\autolevel.exe`（控制台 CLI，约 43 MB）。两者都是 onefile 且自包含。

## 命令行

```powershell
autolevel list             # 当前在播什么，电平多少
autolevel monitor          # 实时电平，不做任何修改
autolevel run              # 持续平衡
autolevel run --dry-run    # 只显示将要施加的增益，不实际写入
autolevel gui              # 打开窗口
```

`run` 会打印实时表格，并且只在运行期间占用你的音量。按 Ctrl+C 会把每个应用恢复到启动前的音量。

```
  应用                     电平     增益  电平条                    状态
  ---------------------- ------- -------  ------------------------  ------
  chrome.exe                -6.0   -12.0  ####################....  活跃
  spotify.exe              -21.4     0.0  ##############..........  活跃
  discord.exe                 --     0.0  ........................  静音
```

常用参数：

```powershell
autolevel run --target -22               # 更安静的共同电平
autolevel run --exclude obs64.exe        # 不要碰录制软件
autolevel run --only chrome.exe,vlc.exe  # 只管理这几个
autolevel run --slew 3                   # 更平缓的音量变化
```

## 视频开始时暂停音乐

勾选**视频播放时暂停音乐**。开始播放 YouTube 视频时 Spotify 会停下；关掉标签页后 Spotify 会在几秒内恢复。

```powershell
autolevel media                          # 列出媒体会话及其应用 ID
autolevel run --autopause                # 视频播放期间暂停音乐
autolevel run --autopause --autopause-action duck   # 改为降低音量
autolevel run --autopause --music vlc --trigger chrome,discord
```

它控制的是**某个具名应用**的传输控制，而不是发送全局播放/暂停键 —— Windows 会把它派发给当前占用媒体控制权的应用，很可能正是你刚打开的那个视频。

以下行为是刻意如此设计的：

- 视频必须持续播放 `0.4 s` 才会触发，所以拖动进度条或看三秒钟的短片不会打断你的音乐。
- 只会恢复**它**暂停的音乐。你自己暂停的音乐保持暂停。
- 如果视频还在播放时你按了音乐播放，它会把此理解为你的意图，并在该视频剩余时间内不再干预，而不是反复和你抢。
- duck 模式是作为偏移量在平衡器内部施加的，所以压低和电平平衡永远不会争抢同一个音量滑块。

## Discord 里有人说话时降低音乐

语音是同一功能的另一半，它需要不同的机制。Discord、Teams 和 Zoom **根本不注册媒体会话** —— 媒体层看不到通话正在进行。它们有的是音频电平，所以语音改用响度来检测。

```powershell
autolevel run --autopause --voice discord
autolevel run --autopause --voice discord,teams --voice-action pause
```

在图形界面里，**语音**标签页会为每个应用列出独立复选框：

```
autopause_voice_apps
# 这些应用的语音活动会压低音乐。取消勾选只是停用而不会丢掉条目；
# 移除才会真正删除。

  ☑ discord                                          移除
  ☐ teams                                            移除
  ☑ zoom                                             移除

  [ obs64            ]  [ 添加 ]
```

**取消勾选**只是停用而保留在列表里 —— 今晚不想让 Discord 触发，不该意味着明天还要重新输入一遍。**移除**才会真正删除。**添加**会追加新条目，重复项会被拒绝。

被停用的应用单独存于 `autopause_voice_disabled`，因此名单得以保留、配置档会携带开关状态，而在这个字段出现之前写下的配置也能照常载入。

语音默认是**压低**而不是暂停。因为有人说了一个词就把音乐掐断，比把音量降下来更糟；如果你不同意，可以把 `autopause_voice_action` 设为 `pause`。

使用中有两个细节值得注意：

- **保持时间用来跨越词与词之间的空隙。** 说话充满了短暂的静默；朴素的门限会让音乐在句子之间反复抽动。`autopause_voice_hold_s`（1.5 秒）让压低状态覆盖这些空隙。
- **视频优先于语音。** 如果你一边在看视频、一边有人在说话，则以视频的动作为准；两者切换时会先释放旧响应，所以压低永远不会残留在一个暂停之下。

触发用的应用必须对平衡器可见。把 Discord 加进 `exclude`，或在界面里取消勾选它那一行，就不会有电平读数，也就无法检测 —— 配置校验会拒绝这种组合，而不是让它静默失效。

通知提示音是已知的误触发来源：Discord 的提及提示音与其他音频没有区别。`autopause_trigger_min_s` 会过滤掉最短的声响，把 `autopause_voice_gate_db` 调到提示音电平之上也有帮助，但这本质是电平检测，无法区分"提示音"和"说话"。

### "一个视频"到底指什么

**它检测的是浏览器媒体播放，而不是特指 YouTube。** Windows 把浏览器暴露为一个名为 `Chrome` 的媒体会话，带标题和艺术家，但没有 URL。YouTube 会触发 —— Twitch、Netflix、Vimeo 以及标签页里的 SoundCloud 同样会触发。这一层没有能区分它们的 API。

它做对的是实践中最要紧的那个区分：通知提示音或界面音效**不会**注册媒体会话，所以它们不会停掉你的音乐。只有真正的媒体播放才会。

想要更严格的触发条件，就收窄 `autopause_trigger` —— 或者把视频放到第二个浏览器里，只针对那一个触发。

## 为什么平衡和增强走不同的路径

Windows 的会话音量范围是 0.0–1.0。常规平衡控制器无法把滑块推到 100% 以上，所以它把响的应用往目标电平拉，把安静的应用留在原样。没有真实增强时，请把目标设在最安静的常用应用附近，然后把系统主音量调高一次作为补偿。

真实增强并不会削弱或绕过这一限制。它为被路由到另一个端点的应用使用独立的 WASAPI 回环/DSP/渲染路径。保持两条路径分离，可以避免平衡滑块和增强处理器争抢同一个信号。

## 配置

```powershell
autolevel config          # 显示当前生效的设置
autolevel config --init   # 写入 %APPDATA%\autolevel\config.json
```

| 设置 | 默认值 | 作用 |
| --- | --- | --- |
| `target_db` | `-18.0` | 所有应用被拉向的目标电平 |
| `min_gain_db` | `-30.0` | 单个应用最多被压低多少 |
| `gate_db` | `-50.0` | 低于此电平视为静音，不做处理 |
| `attack_ms` | `150.0` | 电平上升被记录的速度 |
| `release_ms` | `2000.0` | 电平下降被记录的速度 |
| `settle_ms` | `1500.0` | 需要多久的可听音频才去动这个应用 |
| `slew_db_per_s` | `6.0` | 音量变化速度；越小越平缓 |
| `exclude` / `include_only` | `[]` | 按进程名限定范围 |
| `boost_enabled` | `false` | 是否运行超过 100% 的端点桥接 |
| `boost_source_device` | `""` | 接收在 Windows 音量合成器中被选中应用的端点 |
| `boost_output_device` | `""` | 目标扬声器；留空表示使用默认设备 |
| `boost_gain_db` | `6.0` | 施加在源端点上的真实软件正增益 |
| `boost_ceiling_db` | `-1.0` | 防止削波的峰值限幅上限 |
| `boost_sample_rate` | `48000` | WASAPI 桥接采样率 |
| `boost_block_frames` | `480` | 音频块大小；48 kHz 下 480 帧约 10 ms |
| `autopause_enabled` | `false` | 视频播放时暂停音乐 |
| `autopause_trigger` | 各浏览器 | 这些应用的播放会停掉音乐 |
| `autopause_music` | `["spotify"]` | 要暂停或降低的应用 |
| `autopause_action` | `"pause"` | `pause` 停止播放，`duck` 降低音量 |
| `autopause_duck_db` | `-20.0` | 压低多少 |
| `autopause_resume_delay_s` | `2.0` | 音乐恢复前的延迟 |
| `autopause_voice_apps` | `["discord", "teams", "zoom"]` | 语音活动会降低音乐的应用 |
| `autopause_voice_disabled` | `[]` | 上述名单中当前被停用的应用 |
| `autopause_voice_action` | `"duck"` | 语音触发时的动作；也可用 `pause` |
| `autopause_voice_gate_db` | `-45.0` | 超过此电平即视为在说话 |
| `autopause_voice_hold_s` | `1.5` | 在字句空隙间保持压低 |

应用名按不区分大小写的子串匹配，所以 `spotify` 既能覆盖进程 `Spotify.exe`，也能覆盖媒体 ID `SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify`。结尾的 `.exe` 会被忽略，因此直接从 `autolevel list` 里复制名字就能用。

想要更灵敏的修正就调高 `slew_db_per_s`，如果听得出来调整过程就调低它。

## 工作原理

```
枚举会话 ──> IAudioMeterInformation.GetPeakValue   （每应用，20 Hz）
                              │
                              ▼
                    LoudnessTracker   先过噪声门，再在 dB 域做启动/释放包络
                              │        静音或尚未稳定时返回 None
                              ▼
                    GainController    gain = 目标 − 电平，限幅、限速
                              │
                              ▼
                  ISimpleAudioVolume.SetMasterVolume
```

有两条实测事实塑造了这一设计（见 [docs/CALIBRATION.md](docs/CALIBRATION.md)）：

1. 会话峰值表报告的是应用自身的输出，**不会**随会话音量缩放。测量不受我们自己调整的影响，因此这个环路是开环的，不会振荡到静音。
2. 会话音量只能衰减，于是有了上面那条限制。

静音时返回 `None` 而不是某个电平，而 `None` 会让滑块冻结。暂停的应用会保持当前增益，而不会因为"测量到什么都没有"被推到极端。

真实增强独立运行：

```
Windows 按应用路由
          │
          ▼
源渲染端点 ──> WASAPI 回环采集 ──> 正增益
                                        │
                                        ▼
                                  块峰值限幅器
                                        │
                                        ▼
                                  输出扬声器
```

整个桥接过程中音频始终是浮点帧。只有当请求的增益会越过上限时，限幅器才会降低整块的增益，从而避免对单个采样硬削波带来的失真。

## 局限

- **用的是峰值，不是响度。** 真正的感知响度是带 K 加权、长积分窗口的 LUFS。峰值表只是一个更粗糙的替代指标；在相同主观音量下，密集压缩过的音频读数会比稀疏音频更响。
- **一个进程一个会话。** 所有 Chrome 标签页共用 `chrome.exe`，所以它们是一起被平衡的，无法各自独立。
- **从托盘退出，不要强杀。** 恢复原始音量发生在正常退出时。如果进程被强制结束，Windows 会保留最后一次设定的音量 —— 没有代码能再把它放回去。重新启动后会重新接管同一批应用，所以这是可自愈的，而不是永久损坏。
- **会自己设置音量的应用会和它打架。** 把它加进 `exclude`。
- **独占模式（WASAPI exclusive）的音频流完全绕过混音器**，既看不到也无法控制。
- **增强的选择是端点级的。** 由 Windows 音量合成器决定哪些应用输入到源端点；路由到那里的所有应用共用一个增强增益。
- **增强会带来缓冲延迟。** 默认 480 帧的块在 48 kHz 下约 10 ms，但设备与 Windows 音频引擎共同决定最终的采集到播放总延迟。

## 开发

```powershell
.venv\Scripts\python.exe -m pytest -q      # 全量测试；不需要声卡
.venv\Scripts\python.exe -m pytest -q tests/test_dsp.py::test_gain_changes_are_slew_limited
```

`dsp.py`、增强处理器和 `config.py` 都是纯逻辑，有单元测试覆盖。`sessions.py` 是项目中唯一声明或调用音频会话 COM 接口的模块。`boost.py` 在持有音频流的线程上初始化 COM，并通过 SoundCard 访问 WASAPI。

## 可能的下一步

- 记住每个应用的电平，启动时即可修正，而不必花一两秒重新学习
- 按输出设备区分的配置档；耳机和扬声器想要不同的目标
- "向最安静的应用看齐"的自适应目标，而不是固定值
- 带 K 加权和更长积分窗口的真正 LUFS 测量
- 可选地自动配置 Windows 的按应用端点路由
