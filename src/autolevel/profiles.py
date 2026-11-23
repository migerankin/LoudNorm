"""Named setting snapshots.

A profile is a complete saved copy of the settings. Switching to one loads it
into your current settings -- it does not layer on top of them and it is not a
second source of truth. ``config.json`` always holds what is actually in effect;
``profiles.json`` is a library of snapshots you can recall.

That keeps the mental model to one sentence, at the cost of profiles going stale
if you edit settings afterwards. ``ProfileLibrary.matching`` exists to spot that,
so the UI can say "Gaming (modified)" rather than lying about which is active.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from pathlib import Path

from .config import Config, default_config_path

CONFIG_KEYS = {f.name for f in fields(Config)}

#: Seeded on first run. Starting points, not sacred values.
STARTER_PROFILES: dict[str, dict] = {
    "游戏": {
        # Games are dynamic and you want them present, so sit higher and react
        # quickly. Never hard-pause anything mid-session; duck instead.
        "target_db": -14.0,
        "slew_db_per_s": 9.0,
        "release_ms": 1200.0,
        "autopause_enabled": True,
        "autopause_action": "duck",
        "autopause_duck_db": -18.0,
        "autopause_voice_action": "duck",
        # Sensitive, and holds longer: catching a quiet teammate matters more
        # than the music coming back a second sooner.
        "autopause_voice_gate_db": -48.0,
        "autopause_voice_hold_s": 2.0,
    },
    "休闲": {
        # Quieter overall and slower moving, so corrections stay inaudible. If
        # you put a video on, the music should get out of the way entirely.
        "target_db": -20.0,
        "slew_db_per_s": 4.0,
        "release_ms": 2500.0,
        "autopause_enabled": True,
        "autopause_action": "pause",
        "autopause_duck_db": -14.0,
        "autopause_voice_action": "duck",
        "autopause_voice_gate_db": -45.0,
        "autopause_voice_hold_s": 1.5,
    },
}

#: Shown by the profile selector when settings drifted from, or match no,
#: saved profile. Kept here so the CLI and the GUI agree on the exact suffix.
MODIFIED_SUFFIX = "（已修改）"
UNSAVED_LABEL = "（未保存）"


def default_profiles_path() -> Path:
    return default_config_path().with_name("profiles.json")


def starter_library() -> dict[str, Config]:
    base = Config()
    return {name: replace(base, **overrides) for name, overrides in STARTER_PROFILES.items()}


class ProfileLibrary:
    """The saved profiles, plus which one was last activated."""

    def __init__(self, profiles: dict[str, Config], active: str | None, path: Path):
        self.profiles = profiles
        self.active = active
        self.path = path
        #: Names skipped at load time because they no longer validate.
        self.skipped: list[str] = []

    # --- persistence ---------------------------------------------------------- #

    @classmethod
    def load(cls, path: Path | None = None, seed: bool = True) -> "ProfileLibrary":
        """Read the library. Never raises for a bad file -- a broken profile must
        not stop the app from starting."""
        path = path or default_profiles_path()

        if not path.exists():
            library = cls(starter_library() if seed else {}, None, path)
            if seed:
                try:
                    library.save()
                except OSError:
                    pass  # read-only location; profiles just won't persist
            return library

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(starter_library() if seed else {}, None, path)

        profiles: dict[str, Config] = {}
        skipped: list[str] = []
        for name, data in (raw.get("profiles") or {}).items():
            if not isinstance(data, dict):
                skipped.append(name)
                continue
            # Unknown keys are dropped rather than fatal, so a profile written by
            # a newer build still loads in an older one.
            known = {k: v for k, v in data.items() if k in CONFIG_KEYS}
            try:
                config = Config(**known)
                config.validate()
            except (TypeError, ValueError):
                skipped.append(name)
                continue
            profiles[str(name)] = config

        active = raw.get("active")
        if active not in profiles:
            active = None

        library = cls(profiles, active, path)
        library.skipped = skipped
        return library

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active": self.active,
            "profiles": {name: asdict(config) for name, config in self.profiles.items()},
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self.path

    # --- queries -------------------------------------------------------------- #

    def names(self) -> list[str]:
        return sorted(self.profiles, key=str.lower)

    def get(self, name: str) -> Config | None:
        return self.profiles.get(name)

    def matching(self, config: Config) -> str | None:
        """Name of the profile these settings exactly equal, if any.

        Used to tell "you are on Gaming" from "you started on Gaming and have
        since changed things".
        """
        for name, saved in self.profiles.items():
            if saved == config:
                return name
        return None

    def label_for(self, config: Config) -> str:
        """What the profile selector should display."""
        exact = self.matching(config)
        if exact is not None:
            return exact
        if self.active and self.active in self.profiles:
            return f"{self.active}{MODIFIED_SUFFIX}"
        return UNSAVED_LABEL

    # --- mutation -------------------------------------------------------------- #

    def exists(self, name: str) -> bool:
        return name.strip() in self.profiles

    def put(self, name: str, config: Config, overwrite: bool = True) -> None:
        """Store a profile.

        ``overwrite=False`` makes creating a new profile refuse to clobber an
        existing one, so the UI can ask first instead of silently replacing it.
        """
        name = self.validate_name(name)
        if not overwrite and name in self.profiles:
            raise ValueError(f"已存在名为 {name!r} 的配置档")
        config.validate()
        self.profiles[name] = config

    @staticmethod
    def validate_name(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("配置档必须有名称")
        if len(name) > 40:
            raise ValueError("配置档名称不能超过 40 个字符")
        return name

    def delete(self, name: str) -> bool:
        if name not in self.profiles:
            return False
        del self.profiles[name]
        if self.active == name:
            self.active = None
        return True

    def duplicate(self, name: str, new_name: str) -> None:
        source = self.profiles.get(name)
        if source is None:
            raise ValueError(f"没有名为 {name!r} 的配置档")
        self.put(new_name, replace(source), overwrite=False)

    def rename(self, old: str, new: str) -> None:
        if old not in self.profiles:
            raise ValueError(f"没有名为 {old!r} 的配置档")
        new = self.validate_name(new)
        if new != old and new in self.profiles:
            raise ValueError(f"已存在名为 {new!r} 的配置档")
        self.profiles[new] = self.profiles.pop(old)
        if self.active == old:
            self.active = new

    def activate(self, name: str) -> Config:
        """Mark a profile active and return its settings."""
        config = self.profiles.get(name)
        if config is None:
            raise ValueError(f"没有名为 {name!r} 的配置档")
        self.active = name
        return config
