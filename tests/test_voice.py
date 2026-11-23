from autolevel.autopause import (
    VIDEO,
    VOICE,
    AutoPauseEngine,
    AutoPauseSettings,
    Intent,
    VoiceDetector,
)
from autolevel.mediasessions import STATUS_PAUSED, STATUS_PLAYING, MediaSession, matches

CHROME = "Chrome"
SPOTIFY = "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"


def playing(app_id):
    return MediaSession(app_id=app_id, status=STATUS_PLAYING)


def paused(app_id):
    return MediaSession(app_id=app_id, status=STATUS_PAUSED)


def settings(**kw):
    base = dict(
        enabled=True, trigger_apps=["chrome"], music_apps=["spotify"],
        voice_apps=["discord"], voice_action="duck",
        trigger_min_s=0.4, resume_delay_s=2.0,
    )
    base.update(kw)
    return AutoPauseSettings(**base)


# --- pattern matching -------------------------------------------------------- #

def test_one_pattern_covers_process_name_and_media_id():
    assert matches("Spotify.exe", ["spotify"])
    assert matches(SPOTIFY, ["spotify"])


def test_process_name_with_exe_matches_a_media_id():
    """`autolevel list` prints 'chrome.exe'; the media id is just 'Chrome'.

    Without stripping .exe this fails silently and the trigger never fires.
    """
    assert matches("Chrome", ["chrome.exe"])
    assert matches("chrome.exe", ["chrome.exe"])


def test_matching_is_case_insensitive():
    assert matches("DISCORD.EXE", ["discord"])


def test_unrelated_names_do_not_match():
    assert not matches("chrome.exe", ["spotify"])


def test_empty_patterns_match_nothing():
    assert not matches("chrome.exe", [])
    assert not matches("chrome.exe", ["", "   "])


# --- the detector ----------------------------------------------------------- #

def test_loud_app_counts_as_talking():
    detector = VoiceDetector(gate_db=-45.0)
    assert detector.update({"discord.exe": -20.0}, 0.0) == {"discord.exe"}


def test_quiet_app_does_not_count():
    detector = VoiceDetector(gate_db=-45.0)
    assert detector.update({"discord.exe": -60.0}, 0.0) == set()


def test_hold_bridges_the_gaps_between_words():
    """Speech is full of short gaps; the music must not stutter through them."""
    detector = VoiceDetector(gate_db=-45.0, hold_s=1.5)
    detector.update({"discord.exe": -20.0}, 0.0)
    assert detector.update({"discord.exe": -80.0}, 0.5) == {"discord.exe"}
    assert detector.update({"discord.exe": -80.0}, 1.4) == {"discord.exe"}


def test_activity_expires_after_the_hold():
    detector = VoiceDetector(gate_db=-45.0, hold_s=1.5)
    detector.update({"discord.exe": -20.0}, 0.0)
    assert detector.update({"discord.exe": -80.0}, 2.0) == set()


def test_talking_again_extends_the_hold():
    detector = VoiceDetector(gate_db=-45.0, hold_s=1.5)
    detector.update({"discord.exe": -20.0}, 0.0)
    detector.update({"discord.exe": -20.0}, 1.0)
    assert detector.update({"discord.exe": -80.0}, 2.2) == {"discord.exe"}


def test_detector_tracks_several_apps():
    detector = VoiceDetector(gate_db=-45.0)
    active = detector.update({"discord.exe": -20.0, "teams.exe": -60.0}, 0.0)
    assert active == {"discord.exe"}


def test_reset_clears_activity():
    detector = VoiceDetector(gate_db=-45.0, hold_s=5.0)
    detector.update({"discord.exe": -20.0}, 0.0)
    detector.reset()
    assert detector.update({}, 0.1) == set()


# --- voice driving the engine ----------------------------------------------- #

def test_sustained_voice_ducks_the_music():
    engine = AutoPauseEngine(settings())
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    intents = engine.update([playing(SPOTIFY)], 0.5, voice_active={"discord.exe"})
    assert intents == [Intent("duck", "spotify")]
    assert engine.kind == VOICE


def test_a_blip_of_voice_does_nothing():
    """A notification ping must not duck the music."""
    engine = AutoPauseEngine(settings(trigger_min_s=0.4))
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    assert engine.update([playing(SPOTIFY)], 0.2, voice_active=set()) == []
    assert not engine.active


def test_music_returns_after_the_call_goes_quiet():
    engine = AutoPauseEngine(settings(resume_delay_s=2.0))
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    engine.update([playing(SPOTIFY)], 0.5, voice_active={"discord.exe"})

    engine.update([playing(SPOTIFY)], 1.0, voice_active=set())
    assert engine.update([playing(SPOTIFY)], 3.5, voice_active=set()) == [
        Intent("unduck", "spotify")
    ]
    assert not engine.active


def test_voice_can_be_configured_to_pause_instead():
    engine = AutoPauseEngine(settings(voice_action="pause"))
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    assert engine.update([playing(SPOTIFY)], 0.5, voice_active={"discord.exe"}) == [
        Intent("pause", SPOTIFY)
    ]


def test_unlisted_noisy_app_is_not_a_voice_trigger():
    engine = AutoPauseEngine(settings())
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"chrome.exe"})
    assert engine.update([playing(SPOTIFY)], 5.0, voice_active={"chrome.exe"}) == []


def test_music_cannot_be_its_own_voice_trigger():
    """Spotify's own output must never duck Spotify."""
    engine = AutoPauseEngine(settings(voice_apps=["spotify"]))
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"Spotify.exe"})
    assert engine.update([playing(SPOTIFY)], 5.0, voice_active={"Spotify.exe"}) == []
    assert not engine.active


def test_voice_trigger_is_named_in_the_label():
    engine = AutoPauseEngine(settings())
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    engine.update([playing(SPOTIFY)], 0.5, voice_active={"discord.exe"})
    assert "discord" in engine.trigger_label


# --- both at once ----------------------------------------------------------- #

def test_video_takes_priority_over_voice():
    """Watching something is the stronger signal, so it gets the stronger action."""
    engine = AutoPauseEngine(settings(action="pause", voice_action="duck"))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    intents = engine.update([playing(CHROME), playing(SPOTIFY)], 0.5, voice_active={"discord.exe"})

    assert engine.kind == VIDEO
    assert Intent("pause", SPOTIFY) in intents


def test_switching_from_voice_to_video_undoes_the_duck():
    """A duck left underneath a pause would silently survive the whole session."""
    engine = AutoPauseEngine(settings(action="pause", voice_action="duck"))
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    engine.update([playing(SPOTIFY)], 0.5, voice_active={"discord.exe"})
    assert engine.kind == VOICE

    engine.update([playing(CHROME), playing(SPOTIFY)], 1.0, voice_active={"discord.exe"})
    intents = engine.update([playing(CHROME), playing(SPOTIFY)], 1.6, voice_active={"discord.exe"})

    assert Intent("unduck", "spotify") in intents
    assert engine.kind == VIDEO


def test_falling_back_from_video_to_voice_reapplies_the_duck():
    engine = AutoPauseEngine(settings(action="pause", voice_action="duck", resume_delay_s=1.0))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5, voice_active={"discord.exe"})
    assert engine.kind == VIDEO

    engine.update([paused(CHROME), playing(SPOTIFY)], 1.0, voice_active={"discord.exe"})
    intents = engine.update([paused(CHROME), playing(SPOTIFY)], 2.5, voice_active={"discord.exe"})

    assert engine.kind == VOICE
    assert Intent("play", SPOTIFY) in intents
    assert Intent("duck", "spotify") in intents


def test_reset_clears_a_voice_duck():
    engine = AutoPauseEngine(settings())
    engine.update([playing(SPOTIFY)], 0.0, voice_active={"discord.exe"})
    engine.update([playing(SPOTIFY)], 0.5, voice_active={"discord.exe"})

    assert engine.reset() == [Intent("unduck", "spotify")]
    assert not engine.active
