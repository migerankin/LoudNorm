from autolevel.autopause import AutoPauseEngine, AutoPauseSettings, Intent
from autolevel.mediasessions import STATUS_PAUSED, STATUS_PLAYING, MediaSession

CHROME = "Chrome"
SPOTIFY = "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"


def playing(app_id, title=""):
    return MediaSession(app_id=app_id, status=STATUS_PLAYING, title=title)


def paused(app_id, title=""):
    return MediaSession(app_id=app_id, status=STATUS_PAUSED, title=title)


def settings(**kw):
    base = dict(enabled=True, trigger_apps=["chrome"], music_apps=["spotify"],
                trigger_min_s=0.4, resume_delay_s=2.0, override_grace_s=2.5)
    base.update(kw)
    return AutoPauseSettings(**base)


def engage(engine, t=0.0):
    """Get past the trigger debounce. Returns the time after engaging."""
    engine.update([playing(CHROME), playing(SPOTIFY)], t)
    return t


# --- arming ---------------------------------------------------------------- #

def test_disabled_engine_does_nothing():
    engine = AutoPauseEngine(settings(enabled=False))
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 0.0) == []


def test_brief_video_does_not_stop_the_music():
    """A short clip or a scrub must not interrupt playback."""
    engine = AutoPauseEngine(settings(trigger_min_s=0.4))
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 0.0) == []
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 0.2) == []
    assert not engine.active


def test_sustained_video_pauses_the_music():
    engine = AutoPauseEngine(settings())
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    intents = engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)
    assert intents == [Intent("pause", SPOTIFY)]
    assert engine.active


def test_music_that_is_already_paused_is_left_alone():
    engine = AutoPauseEngine(settings())
    engine.update([playing(CHROME), paused(SPOTIFY)], 0.0)
    assert engine.update([playing(CHROME), paused(SPOTIFY)], 0.5) == []


def test_music_started_during_a_video_is_also_paused():
    engine = AutoPauseEngine(settings())
    engine.update([playing(CHROME)], 0.0)
    engine.update([playing(CHROME)], 0.5)
    intents = engine.update([playing(CHROME), playing(SPOTIFY)], 1.0)
    assert intents == [Intent("pause", SPOTIFY)]


def test_trigger_label_reports_what_is_playing():
    engine = AutoPauseEngine(settings())
    engine.update([playing(CHROME, "Some Video")], 0.0)
    engine.update([playing(CHROME, "Some Video")], 0.5)
    assert "Some Video" in engine.trigger_label


# --- resuming -------------------------------------------------------------- #

def test_music_resumes_after_the_video_stops():
    engine = AutoPauseEngine(settings(resume_delay_s=2.0))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)

    engine.update([paused(CHROME), paused(SPOTIFY)], 1.0)
    assert engine.update([paused(CHROME), paused(SPOTIFY)], 3.5) == [Intent("play", SPOTIFY)]
    assert not engine.active


def test_resume_waits_for_the_delay():
    """Skipping between videos must not flap the music on and off."""
    engine = AutoPauseEngine(settings(resume_delay_s=2.0))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)

    engine.update([paused(CHROME), paused(SPOTIFY)], 1.0)
    assert engine.update([paused(CHROME), paused(SPOTIFY)], 2.0) == []
    assert engine.active


def test_music_the_user_paused_is_not_resumed():
    engine = AutoPauseEngine(settings())
    engine.update([playing(CHROME), paused(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), paused(SPOTIFY)], 0.5)

    engine.update([paused(CHROME), paused(SPOTIFY)], 1.0)
    assert engine.update([paused(CHROME), paused(SPOTIFY)], 4.0) == []


# --- user override --------------------------------------------------------- #

def test_manual_restart_during_a_video_is_respected():
    """If the user presses play again, stop interfering for this run."""
    engine = AutoPauseEngine(settings(override_grace_s=2.5))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 0.5) == [Intent("pause", SPOTIFY)]

    # Still playing well past the grace period: the user restarted it.
    engine.update([playing(CHROME), playing(SPOTIFY)], 3.5)
    assert SPOTIFY not in engine.paused_apps

    # And we must not pause it again.
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 5.0) == []


def test_pause_is_not_repeated_within_the_grace_period():
    """Windows takes a moment to apply the pause; don't spam it."""
    engine = AutoPauseEngine(settings(override_grace_s=2.5))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 1.0) == []


def test_overridden_music_is_not_resumed_later():
    engine = AutoPauseEngine(settings())
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)
    engine.update([playing(CHROME), playing(SPOTIFY)], 3.5)  # override registered

    engine.update([paused(CHROME), playing(SPOTIFY)], 4.0)
    assert engine.update([paused(CHROME), playing(SPOTIFY)], 7.0) == []


# --- ducking --------------------------------------------------------------- #

def test_duck_mode_lowers_instead_of_pausing():
    engine = AutoPauseEngine(settings(action="duck"))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 0.5) == [Intent("duck", "spotify")]


def test_duck_is_released_when_the_video_stops():
    engine = AutoPauseEngine(settings(action="duck", resume_delay_s=1.0))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)

    engine.update([paused(CHROME), playing(SPOTIFY)], 1.0)
    assert engine.update([paused(CHROME), playing(SPOTIFY)], 2.5) == [Intent("unduck", "spotify")]


def test_duck_is_applied_only_once():
    engine = AutoPauseEngine(settings(action="duck"))
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 1.0) == []


# --- safety ---------------------------------------------------------------- #

def test_music_app_cannot_trigger_against_itself():
    """Overlapping patterns must not make Spotify pause Spotify."""
    engine = AutoPauseEngine(settings(trigger_apps=["spotify"], music_apps=["spotify"]))
    engine.update([playing(SPOTIFY)], 0.0)
    assert engine.update([playing(SPOTIFY)], 5.0) == []
    assert not engine.active


def test_unrelated_apps_are_ignored():
    engine = AutoPauseEngine(settings())
    engine.update([playing("SomeGame.exe"), playing(SPOTIFY)], 0.0)
    assert engine.update([playing("SomeGame.exe"), playing(SPOTIFY)], 5.0) == []


def test_reset_releases_everything():
    engine = AutoPauseEngine(settings())
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)

    assert engine.reset() == [Intent("play", SPOTIFY)]
    assert not engine.active
    assert engine.paused_apps == set()


def test_disabling_mid_run_resumes_the_music():
    config = settings()
    engine = AutoPauseEngine(config)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.0)
    engine.update([playing(CHROME), playing(SPOTIFY)], 0.5)

    config.enabled = False
    assert engine.update([playing(CHROME), playing(SPOTIFY)], 1.0) == [Intent("play", SPOTIFY)]
