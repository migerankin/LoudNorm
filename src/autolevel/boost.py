"""Above-unity audio gain through a WASAPI endpoint bridge.

Windows application volume sliders attenuate only.  This module provides the
separate DSP path needed for real boost: selected applications are routed to a
source render endpoint, its loopback is captured, samples are amplified and
peak-limited, then rendered to the listener's output endpoint.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import MAX_BOOST_GAIN_DB


def _initialize_com():
    """Initialize COM on the current audio thread and return its cleanup."""
    import comtypes

    comtypes.CoInitialize()
    return comtypes.CoUninitialize


@dataclass(frozen=True)
class BoostSettings:
    source_device: str
    output_device: str = ""
    gain_db: float = 6.0
    ceiling_db: float = -1.0
    sample_rate: int = 48_000
    block_frames: int = 480


@dataclass(frozen=True)
class OutputDevice:
    id: str
    name: str
    is_default: bool
    can_loopback: bool


def settings_from_config(config) -> BoostSettings:
    """Take a stable snapshot of the bridge fields for a worker thread."""
    return BoostSettings(
        source_device=config.boost_source_device,
        output_device=config.boost_output_device,
        gain_db=config.boost_gain_db,
        ceiling_db=config.boost_ceiling_db,
        sample_rate=int(config.boost_sample_rate),
        block_frames=int(config.boost_block_frames),
    )


class BoostProcessor:
    """Apply real linear gain while keeping every sample below a dBFS ceiling."""

    def __init__(self, gain_db: float, ceiling_db: float = -1.0):
        if not math.isfinite(gain_db) or not math.isfinite(ceiling_db):
            raise ValueError("增强增益与上限必须是有限数值")
        if gain_db <= 0.0:
            raise ValueError("增强增益必须大于 0 dB")
        if gain_db > MAX_BOOST_GAIN_DB:
            raise ValueError(f"增强增益不能超过 {MAX_BOOST_GAIN_DB:g} dB")
        if ceiling_db > 0.0:
            raise ValueError("增强上限必须不高于 0 dBFS")
        self.gain_db = gain_db
        self.ceiling_db = ceiling_db
        self.applied_gain_db = gain_db
        self.limiter_reduction_db = 0.0
        self.output_peak = 0.0

    def process(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        """Return an amplified copy of a ``frames x channels`` float array.

        A transparent block peak limiter lowers this block's gain just enough to
        avoid clipping. It never hard-clips individual samples, which would add
        avoidable distortion.
        """
        del sample_rate  # reserved for a stateful release stage
        source = np.nan_to_num(
            np.asarray(samples, dtype=np.float32),
            copy=True,
            nan=0.0,
            posinf=1.0,
            neginf=-1.0,
        )
        requested = 10.0 ** (self.gain_db / 20.0)
        ceiling = 10.0 ** (self.ceiling_db / 20.0)
        input_peak = float(np.max(np.abs(source))) if source.size else 0.0
        safe = requested if input_peak == 0.0 else min(requested, ceiling / input_peak)

        self.applied_gain_db = 20.0 * math.log10(safe) if safe > 0.0 else -120.0
        self.limiter_reduction_db = min(0.0, self.applied_gain_db - self.gain_db)
        result = np.clip(source * safe, -ceiling, ceiling)
        self.output_peak = float(np.max(np.abs(result))) if result.size else 0.0
        return result


def _audio_module():
    import soundcard

    return soundcard


def list_output_devices(audio: Any | None = None) -> list[OutputDevice]:
    """List render endpoints and whether WASAPI exposes loopback capture."""
    audio = audio or _audio_module()
    default = audio.default_speaker()
    loopback_ids = {
        microphone.id
        for microphone in audio.all_microphones(include_loopback=True)
        if getattr(microphone, "isloopback", False)
    }
    return [
        OutputDevice(
            id=speaker.id,
            name=speaker.name,
            is_default=speaker.id == default.id,
            can_loopback=speaker.id in loopback_ids,
        )
        for speaker in audio.all_speakers()
    ]


def _resolve(endpoints, value: str, kind: str):
    wanted = value.strip().casefold()
    exact = [
        endpoint
        for endpoint in endpoints
        if wanted in (str(endpoint.id).casefold(), str(endpoint.name).casefold())
    ]
    if len(exact) == 1:
        return exact[0]

    partial = [endpoint for endpoint in endpoints if wanted in str(endpoint.name).casefold()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise ValueError(f"找不到增强{kind}设备 {value!r}")
    names = ", ".join(endpoint.name for endpoint in partial)
    raise ValueError(f"增强{kind}设备 {value!r} 不唯一，匹配到：{names}")


class BoostBridge(threading.Thread):
    """Capture, amplify and render continuously on a private worker thread."""

    def __init__(self, settings: BoostSettings, audio: Any | None = None):
        super().__init__(daemon=True, name="autolevel-boost")
        self.settings = settings
        self._audio = audio
        self._stop_event = threading.Event()
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.processor = BoostProcessor(settings.gain_db, settings.ceiling_db)
        self.frames_processed = 0
        self.max_output_peak = 0.0

    @property
    def status(self) -> str:
        if self.error is not None:
            return f"增强不可用：{self.error}"
        if self.ready.is_set() and self.is_alive():
            reduction = self.processor.limiter_reduction_db
            limited = f"，限幅器已压 {abs(reduction):.1f} dB" if reduction < -0.05 else ""
            return f"增强中 +{self.settings.gain_db:.1f} dB{limited}"
        return "增强已停止"

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        uninitialize_com = None
        try:
            uninitialize_com = _initialize_com()
            audio = self._audio or _audio_module()
            loopbacks = [
                endpoint
                for endpoint in audio.all_microphones(include_loopback=True)
                if getattr(endpoint, "isloopback", False)
            ]
            source = _resolve(loopbacks, self.settings.source_device, "源")
            output = (
                _resolve(audio.all_speakers(), self.settings.output_device, "输出")
                if self.settings.output_device.strip()
                else audio.default_speaker()
            )
            if source.id == output.id:
                raise ValueError(
                    "增强的源端点与输出端点必须是不同设备，否则会形成回授"
                )

            stream_args = {
                "samplerate": self.settings.sample_rate,
                "channels": 2,
                "blocksize": self.settings.block_frames,
            }
            with source.recorder(**stream_args) as recorder, output.player(**stream_args) as player:
                self.ready.set()
                while not self._stop_event.is_set():
                    captured = recorder.record(numframes=self.settings.block_frames)
                    rendered = self.processor.process(captured, self.settings.sample_rate)
                    player.play(rendered)
                    self.frames_processed += len(rendered)
                    self.max_output_peak = max(
                        self.max_output_peak, self.processor.output_peak
                    )
        except BaseException as exc:
            self.error = exc
        finally:
            if uninitialize_com is not None:
                uninitialize_com()
            self.ready.set()


class BoostSession:
    """Own an optional bridge and guarantee cleanup on every caller exit path."""

    def __init__(self, config, dry_run: bool = False, bridge_factory=BoostBridge):
        self.config = config
        self.dry_run = dry_run
        self._bridge_factory = bridge_factory
        self.bridge = None
        self._stopping = False

    @property
    def status(self) -> str:
        if not self.config.boost_enabled:
            return ""
        if self.dry_run:
            return "试运行中不启用增强"
        if self._stopping:
            return "增强正在停止，等待音频流结束"
        return self.bridge.status if self.bridge is not None else "增强已停止"

    def start(self, timeout: float = 5.0) -> None:
        if not self.config.boost_enabled or self.dry_run:
            return
        if self.bridge is not None:
            if self.bridge.is_alive():
                raise RuntimeError("上一个增强桥接仍在停止中")
            self.bridge = None
            self._stopping = False
        self.bridge = self._bridge_factory(settings_from_config(self.config))
        try:
            self.bridge.start()
        except BaseException:
            self.close()
            raise
        if not self.bridge.ready.wait(timeout):
            self.close()
            raise RuntimeError("增强音频端点未在超时前就绪")
        if self.bridge.error is not None:
            error = self.bridge.error
            self.close()
            raise RuntimeError(f"无法启动真实增强：{error}") from error

    def close(self, timeout: float | None = 3.0) -> bool:
        bridge = self.bridge
        if bridge is None:
            return True
        self._stopping = True
        bridge.stop()
        try:
            bridge.join(timeout)
        except RuntimeError:
            if bridge.is_alive():
                raise
        if bridge.is_alive():
            return False
        self.bridge = None
        self._stopping = False
        return True
