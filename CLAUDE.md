# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
uv venv --python 3.11 .venv                                  # create the venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]" # install editable
.venv\Scripts\python.exe -m pytest -q                        # full suite
.venv\Scripts\python.exe -m pytest -q tests/test_dsp.py      # one file
.venv\Scripts\python.exe -m pytest -q -k slew                # one test by name
.venv\Scripts\autolevel.exe list                             # manual smoke check
.venv\Scripts\python.exe -m autolevel gui                    # run the GUI from source
.\build.ps1                                                  # build dist\*.exe
```

The venv must be Python 3.11 — pycaw and comtypes are not verified here on 3.14,
which is this machine's default interpreter. There is no linter configured.

## Architecture

A control loop that reads each application's output level from the Windows Core
Audio session API and writes back that application's volume slider.

```
gui.py / cli.py  ──>  sessions.py  ──>  balancer.py  ──>  dsp.py
   (front ends)          (COM)            (loop)         (pure math)
        │
        ├──────────>  mediasessions.py  ──>  autopause.py
        │                 (WinRT)            (pure state machine)
        └──────────>  boost.py
                          (WASAPI endpoint bridge + pure sample DSP)
```

**Three independent Windows media/audio paths are in play and easy to confuse.**
`sessions.py` is Core Audio (COM): how loud an app is, and its volume slider.
`mediasessions.py` is GSMTC (WinRT): what an app is playing, whether it is
playing, and transport control. They identify apps differently — Core Audio by
process name (`Spotify.exe`), GSMTC by app user model id
(`SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify`). `mediasessions.matches()` does
case-insensitive substring matching so one config pattern covers both.
`boost.py` uses SoundCard's WASAPI endpoint loopback: floating-point audio frames
from every app Windows routed to one source endpoint. It does not identify
processes itself.

The layering is deliberate and worth preserving: **`sessions.py` is the only
module that declares or calls audio-session COM interfaces.** `boost.py` only
initializes/uninitializes COM on the thread that owns SoundCard's WASAPI streams.
`dsp.py` and `config.py` have no Windows dependency, which is why control and
sample processing are unit testable without a sound card. Adding COM calls to
`dsp.py` or `balancer.py` would break that.

Signal path per application, once per 50 ms tick:

1. `ManagedSession.peak()` — `IAudioMeterInformation.GetPeakValue`, 0.0–1.0
2. `LoudnessTracker.update()` — noise gate, then an attack/release envelope in dB
3. `GainController.update()` — `target − level`, clamped, slew limited
4. `ManagedSession.set_volume()` — `ISimpleAudioVolume.SetMasterVolume`

## Two measured constraints that drive the design

Both are documented with evidence in `docs/CALIBRATION.md`. Do not re-derive them
from intuition; they are counterintuitive in opposite directions.

**The peak meter is pre-volume.** It reports what the app produced, unaffected by
the session volume we set. The loop is therefore open-loop. If you ever "fix" the
controller by compensating for applied gain, you will introduce the feedback bug
that this design specifically avoids.

**Session volume attenuates only** (scalar 0.0–1.0). The balancing controller
cannot make apps louder than they already play. `max_gain_db` exists but defaults
to `0.0` and raising it does nothing, because `volume_scalar` clamps at 1.0.
Balancing works by pulling loud apps down, not quiet apps up. True boost is a
separate capture/DSP/render path; do not merge its positive gain into
`GainController` or `ManagedSession.set_volume()`.

## True boost

`boost.py` captures the loopback of one render endpoint, applies positive
floating-point gain with a block peak limiter, and renders to a different
endpoint. Windows Volume Mixer selects apps by routing them to the source. All
apps on that source share one gain; this is endpoint-based, not process capture.

The source and output IDs must differ or the bridge feeds its own output back.
`BoostSession` owns lifecycle for both CLI and GUI: disabled/dry-run means no
stream, startup errors are surfaced, and every exit path calls `close()`. Keep
SoundCard imports lazy enough that normal balancing still starts cleanly.

The bridge renders from the AutoLevel process, so `SessionRegistry` always skips
its own PID. Without that guard the normal balancer attenuates the boosted stream
it just created. Shutdown retains ownership until the WASAPI thread exits; never
clear a live bridge/thread reference after a timed join, because that permits a
second bridge to start against the same endpoints.

Boost settings are read when balancing starts. Changing source, output, gain,
ceiling, sample rate, or block size while running requires a restart because the
live WASAPI streams are not rebound in place.

## Conventions

`LoudnessTracker.update()` returns `None` — not a level — when an app is silent
or has not yet produced enough audio to judge. `GainController.update(None)`
holds the current gain. This `None`-means-hold contract is load-bearing: treating
`None` as a level would drive paused apps to an extreme. Preserve it in any new
code on this path.

Original volumes are captured the first time a session is seen and replayed by
`SessionRegistry.restore_all()`, plus per-session in `refresh()` when a session
disappears. Any new exit path must still restore, or users are left with apps
silently turned down.

All COM calls in `sessions.py` are individually wrapped — sessions can die
between enumeration and use, and that is normal, not exceptional.

Levels are dBFS everywhere internally; linear amplitude appears only at the API
boundary. `SILENCE_DB = -120.0` stands in for negative infinity so the math stays
finite.

## GUI threading

`gui.py` runs the balancer on a worker thread and this arrangement is fragile in
specific ways:

- `SessionRegistry` calls `CoInitialize` in its constructor, so it must be
  **built on the worker thread**, not constructed in the GUI and passed in.
- COM objects never cross threads. The worker publishes frozen `Snapshot`
  objects through a `queue.Queue`; the Tk thread drains it on an `after()` timer.
  Do not put `ManagedSession` or any COM pointer on that queue.
- Do not name a `threading.Thread` attribute `_stop`. `Thread._stop` is a private
  method the interpreter calls during `join()`, and shadowing it makes shutdown
  raise `TypeError: 'Event' object is not callable`. This was a real bug here;
  the attribute is `_stop_event`.
- `BoostBridge` runs a second worker thread. It carries NumPy arrays only and owns
  its SoundCard streams. It must call `CoInitialize` and `CoUninitialize` on that
  thread; source mode can mask the omission while a frozen build fails with
  `0x800401F0`. Never put a recorder/player object on the Tk queue.

## Auto-pause

`autopause.py` is a pure state machine over media snapshots plus an injected
clock — no WinRT, no threads — which is why all 19 of its rules are unit tested.
Keep it that way; put side effects in `AutoPauseRunner`, not `AutoPauseEngine`.

Three rules are behavioural, not incidental, and tests will fail if they are
"simplified" away:

- Only apps in `_paused_at` are resumed. Music the user paused themselves must
  stay paused.
- `_overridden` is permanent for the duration of a trigger. If the user presses
  play while a video is still going, the app stops interfering rather than
  re-pausing in a loop.
- `override_grace_s` exists because Windows takes a moment to apply a pause. An
  app still reporting `playing` immediately after `try_pause_async` is normal;
  only after the grace period does it mean the user intervened.

There are **two trigger classes on two different APIs**, and the split is not
cosmetic:

- `VIDEO` comes from media sessions (GSMTC). Anything registering transport
  controls.
- `VOICE` comes from raw Core Audio peak levels, because Discord, Teams and Zoom
  register no media session at all — the media layer literally cannot see a call.

They carry separate actions (`action` vs `voice_action`, defaulting to pause and
duck). Video wins when both are live, and a class change goes through
`_release()` before engaging the new one — otherwise a duck stays buried under a
pause and never comes back.

Voice levels come from `AppState.peak`, the **raw** peak, not `level_db`. The
settled envelope needs `settle_ms` (1.5 s) of audio before it reports anything,
far too slow for speech. `VoiceDetector`'s hold is what bridges the gaps between
words; without it the music stutters between sentences.

Voice detection reads levels the balancer collects, so an app in `exclude` is
invisible to it. `Config.validate()` rejects that combination rather than letting
it fail silently — but only for apps that are actually switched on, hence
`active_voice_apps()`.

**Auto-pause settings are live and must stay live.** `BalancerThread.autopause` is
a single `AutoPauseSettings` object shared by the thread, the engine, the runner
and the voice detector. `apply_autopause()` copies fields into it **in place** —
rebinding it would leave all four on the old settings, which was a real reported
bug (choosing "pause" kept ducking until you restarted balancing). For the same
reason `AutoPauseRunner.tick` re-reads `voice_gate_db`/`voice_hold_s` into the
detector each tick, and `AutoPauseEngine.update` releases when the **action**
changes and not only when the trigger class does.

Voice apps are two fields: `autopause_voice_apps` is the roster,
`autopause_voice_disabled` the ones switched off. Anything consuming them must go
through `Config.active_voice_apps()`, never the raw roster, or disabled apps
still trigger. Keeping the name rather than deleting it is deliberate: unticking
Discord for an evening must not lose the entry, and a config written before this
field existed still loads because the default is empty.

`matches()` strips a trailing `.exe` from patterns. One pattern has to match both
a process name (`Chrome.exe`) and a media app id (`Chrome`), and the natural
thing to type is what `autolevel list` prints. Without the strip, `chrome.exe`
never matches the media id and the trigger silently never fires — a real bug
caught by a live test, not a hypothetical.

Ducking is applied as `AppState.duck_db`, an offset added to the balancing gain
inside `Balancer.tick`. It is deliberately **not** a direct volume write — two
writers on one session volume would fight at 20 Hz.

`MediaController` runs WinRT on a private asyncio event loop in its own thread.
Never call it from the loop thread; `pause()`/`play()` marshal via
`run_coroutine_threadsafe`. Targeted transport control is the whole point — do
not replace it with a global `VK_MEDIA_PLAY_PAUSE` keystroke, which Windows
routes to whichever app owns media control and would often pause the video
instead of the music.

Detection granularity is the browser, not the site: GSMTC reports `Chrome` with
no URL, so YouTube and Twitch are indistinguishable. Say so rather than implying
site-level detection.

## GUI structure

Three modules, split by job:

- `theme.py` — the only place colours and fonts are defined, plus widget
  factories. Do not hardcode a hex value in `gui.py` or `settingsui.py`; add it
  here. `init_styles()` must run against the root before any ttk widget is
  created, or Notebook/Combobox/Scale render as light-grey Win32 controls in the
  middle of a dark window. It forces the `clam` ttk theme because the native
  Windows themes silently ignore `background`.
- `settingsui.py` — everything configurable. Fields are **declared** in `GROUPS`
  as `Setting` records; adding a config option is one line, not a hand-built row.
  Each row shows its real `config.json` key, so the panel and the file share one
  vocabulary. Kinds are `float`/`int`/`text`/`bool`/`choice`/`list`, plus
  `applist` for the checkbox editor — `applist` is the one kind that spans
  **two** config keys
  (roster and disabled list) and owns its own widget, so it is special-cased in
  `_build_row`, `load`, `load_defaults` and `collect`.
- `gui.py` — the main window, which deliberately holds no configuration beyond
  the target slider and two toggles. New options belong in `settingsui.py`.

Saving goes through `Config.validate()` and reports failures inline. A rejected
save must not mutate the live config — `collect()` builds a candidate with
`dataclasses.replace` and validates it *before* anything is applied.

Combobox dropdowns are Tk listboxes, not ttk widgets, so they need `option_add`
rather than `style.configure`; that is already handled in `init_styles`.

## Profiles

`profiles.py` stores named **complete** copies of `Config` in `profiles.json`.
Switching replaces current settings; it does not merge. `config.json` remains the
single source of what is in effect — resist any change that makes a profile
partially override live settings, because then two files both describe the
current state and neither is authoritative.

`matching()` / `label_for()` exist to keep the UI honest about drift: once
settings differ from the active profile the selector must read
`Gaming (modified)`, not `Gaming`.

`Save` in the settings panel writes `config.json` only — it deliberately does not
touch the active profile, or experimenting would silently rewrite a preset.
`update_profile()` is the explicit way to fold edits back in, and `save()` says so
when `label_for()` reports drift. Both bugs reported here came from that gap being
invisible; keep the message.

Profile creation is split so it is testable without driving a dialog: each
`prompt_*` opens a `NameDialog`, and each verb (`save_as_profile`,
`duplicate_profile`, `rename_profile`, `AutoLevelWindow.create_profile`) takes a
name and **returns an error string or None**. The dialog stays open on a returned
error. Keep that contract when adding new ones.

`put(..., overwrite=False)` exists so creation can refuse to clobber; the header
"+" dialog warns and offers **Replace** instead of silently overwriting.

`ProfileLibrary.load()` never raises. A corrupt file falls back to the starters,
an individual invalid profile is skipped into `.skipped`, and unknown keys are
dropped so a file written by a newer build still loads. A bad profile must not
stop the app from starting.

## Tray and startup

`tray.py` runs pystray's Win32 message loop on its own thread, so **every tray
callback arrives off the Tk thread**. Two rules keep that safe and both are load
bearing:

- Actions are marshalled with `window.after(0, ...)`. Never call a widget method
  from a tray callback.
- Menu check state is read from `window.tray_state`, a plain dict the GUI thread
  maintains. Reading a `BooleanVar` from the tray thread is a cross-thread Tk
  access — it appears to work and then intermittently doesn't.
- **Menu callbacks must take 0, 1 or 2 arguments.** pystray inspects
  `co_argcount` and raises `ValueError` for anything larger, and *default
  arguments count* — so the obvious `lambda n=name: ...` capture blows up at menu
  construction. Use a bound method and read the value off `item.text`, as
  `_on_profile_click` does.

The profile submenu is rebuilt by `refresh_menu()` whenever the library changes;
pystray does not re-evaluate menu structure on its own, only `checked` callables.

Closing the window hides it; only tray Quit sets `_quitting` and actually exits.
Any new exit path must go through `quit_app()`, or balancing survives a "close"
with no way to reach it.

`startup.py` writes one `HKCU\...\Run` value. `launch_command()` handles three
cases and the distinction matters: the windowed exe takes `--minimized`
directly, the console exe does **not** (it needs its `gui` subcommand) and would
fail silently at every logon, and a dev checkout runs `pythonw.exe -m autolevel
gui --minimized`. All three are unit tested with a monkeypatched `sys.frozen`.

`is_current()` exists because moving or rebuilding the exe leaves a stale entry
that also fails silently. Surface staleness; don't just report enabled/disabled.

Note for anything that backs up and restores the logon entry: `set_enabled(True)`
writes the command for *the process calling it*, so restoring from a dev checkout
after reading a frozen entry silently rewrites it to the pythonw form. Back up
and restore the raw registry value, not the boolean.

Tests hit the real registry under a scratch key (`Software\autolevel-test`) and
delete it afterwards — the point of that module is that it talks to the registry
correctly, so mocking it would test nothing.

## Packaging

`build.ps1` produces both executables via PyInstaller onefile. Two things it has
to work around:

- `--collect-all` for `pycaw`, `comtypes`, and `winsdk` is required; all three
  resolve modules by name at runtime, so PyInstaller's static analysis
  misses them and the frozen app fails at *runtime*, not build time. Verify a
  build by running `dist\autolevel.exe media` — it exercises WinRT — not just by checking
  the exe exists.
- Do **not** add `--collect-all soundcard`: SoundCard ships an official
  PyInstaller hook. `collect-all` additionally bundles its tests and pytest,
  bloating both executables without improving the WASAPI backend.
- The script deliberately sets `$ErrorActionPreference = "Continue"`. PyInstaller
  logs progress to stderr, and under Windows PowerShell 5.1 `"Stop"` promotes
  that to a terminating error on a perfectly successful build. Exit codes are
  checked explicitly instead.

The icon is generated, not committed: `packaging/make_icon.py` calls
`iconart.write_ico()`, and `build.ps1` runs it before each build. `iconart.py`
depends only on Pillow so the generator does not drag in pystray.

Onefile launches a bootloader process that extracts and spawns a child; the
window belongs to the **child**. Killing the parent by PID orphans the child, so
clean up by process name when testing. A surviving instance holds a lock on
`dist\*.exe` and PyInstaller reports it as a bare "Access is denied";
`build.ps1` checks for running processes up front and says so plainly.
