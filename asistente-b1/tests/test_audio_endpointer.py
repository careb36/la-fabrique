"""The endpointer is the part users feel: it decides when they stopped talking."""

from b1.audio import Endpointer, frames_to_pcm, pcm_to_floats, rms

FRAME = 480  # 30 ms at 16 kHz
QUIET = [40.0] * FRAME
LOUD = [4000.0] * FRAME


def test_rms_and_pcm_roundtrip():
    assert rms([100.0, -100.0]) == 100.0
    assert rms([]) == 0.0
    pcm = frames_to_pcm([[1000.0, -1000.0, 0.0]])
    assert len(pcm) == 6
    assert pcm_to_floats(pcm) == [1000.0, -1000.0, 0.0]


def test_pcm_clips_instead_of_wrapping():
    pcm = frames_to_pcm([[999999.0, -999999.0]])
    assert pcm_to_floats(pcm) == [32767.0, -32768.0]


def test_ignores_quiet_frames():
    end = Endpointer()
    for _ in range(20):
        assert end.feed(QUIET) is None
    assert end.collecting is False


def test_one_phrase_then_end():
    end = Endpointer(silence_ms=300)
    for _ in range(6):
        end.feed(QUIET)
    assert end.feed(LOUD) is None       # first loud frame only arms the counter
    for _ in range(5):
        end.feed(LOUD)
    assert end.collecting is True

    utterance = None
    for _ in range(30):
        utterance = end.feed(QUIET)
        if utterance:
            break
    assert utterance, "the phrase never closed"
    samples = pcm_to_floats(utterance)
    assert len(samples) > 5 * FRAME
    assert max(samples) >= 3000
    assert end.collecting is False


def test_preroll_keeps_the_start_of_the_word():
    end = Endpointer(preroll_ms=90, silence_ms=300)
    for _ in range(3):
        end.feed(QUIET)
    for _ in range(4):
        end.feed(LOUD)
    for _ in range(20):
        if end.feed(QUIET):
            break
    # 90 ms of preroll + the loud frames, at least.
    assert end.collecting is False


def test_long_monologue_is_cut_at_max_ms():
    end = Endpointer(max_ms=90, silence_ms=10_000)
    for _ in range(3):
        end.feed(LOUD)
    utterance = None
    for _ in range(20):
        utterance = end.feed(LOUD)
        if utterance:
            break
    assert utterance is not None


def test_flush_closes_open_utterance():
    end = Endpointer()
    for _ in range(5):
        end.feed(LOUD)
    assert end.collecting is True
    pcm = end.flush()
    assert pcm and len(pcm) > 0
    assert end.collecting is False
    assert end.flush() is None


def test_noise_floor_adapts_while_idle():
    end = Endpointer()
    start = end.noise_floor
    for _ in range(60):
        end.feed([110.0 + (i % 7) for i in range(FRAME)])
    assert end.noise_floor > start
