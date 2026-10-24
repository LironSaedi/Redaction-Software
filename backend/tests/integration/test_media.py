"""Images, video and audio — vision / speech models run locally."""
import io
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from obscura.detection.vision.tracker import Track, interpolate_keyframes, track
from obscura.detection.vision.detectors import VBox, merge_union
from obscura.redact.audio import merge_ranges, redact_samples
from obscura.redact.effects import apply_effect

FIX = Path(__file__).resolve().parents[1] / "fixtures"


# ---- pure units (fast) ------------------------------------------------------------------------------
@pytest.mark.parametrize("effect", ["blackout", "whiteout", "pixelate", "blur"])
@pytest.mark.parametrize("shape", ["rect", "ellipse"])
def test_effects_change_only_roi(effect, shape):
    img = (np.random.default_rng(0).random((200, 300, 3)) * 255).astype(np.uint8)
    orig = img.copy()
    apply_effect(img, 50, 40, 150, 140, effect, shape=shape)
    assert (img[:40] == orig[:40]).all() and (img[:, 160:] == orig[:, 160:]).all()
    roi_o, roi_n = orig[40:140, 50:150].astype(int), img[40:140, 50:150].astype(int)
    assert np.abs(roi_o - roi_n).mean() > 20  # content inside is destroyed


def test_blackout_is_solid():
    img = np.full((50, 50, 3), 200, np.uint8)
    apply_effect(img, 10, 10, 40, 40, "blackout")
    assert (img[10:40, 10:40] == 0).all()


def test_effect_clips_to_frame():
    img = np.zeros((50, 50, 3), np.uint8)
    apply_effect(img, -20, -20, 500, 500, "whiteout")
    assert (img == 255).all()


def test_merge_union_keeps_largest_extent():
    boxes = [VBox(10, 10, 50, 50, 0.9, "face", "a"), VBox(15, 12, 60, 55, 0.6, "face", "b"), VBox(200, 200, 220, 220, 0.5, "face", "a")]
    m = merge_union(boxes)
    assert len(m) == 2 and (m[0].x0, m[0].y0, m[0].x1, m[0].y1) == (10, 10, 60, 55) and "b" in m[0].source


def _det(f, x, s=0.9):
    return VBox(x, 100, x + 50, 160, s, "face", "t")


def test_tracker_interpolates_gaps_and_rolls():
    dets = {f: [_det(f, 100 + f * 2)] for f in range(30) if f % 4 != 1}  # periodic misses
    tracks = track(dets, 60, 30, 1280, 720)
    assert len(tracks) == 1
    t = tracks[0]
    assert all(f in t.boxes for f in range(0, 30))  # no gaps
    assert max(t.boxes) >= 29 + 10  # post-roll keeps redacting after the last detection


def test_tracker_pre_roll():
    dets = {f: [_det(f, 300)] for f in range(20, 40)}
    t = track(dets, 60, 30, 1280, 720)[0]
    assert min(t.boxes) <= 20 - 5


def test_tracker_padding_and_smoothing_never_shrink():
    dets = {f: [_det(f, 100 + (5 if f % 2 else -5))] for f in range(20)}
    t = track(dets, 20, 30, 1280, 720)[0]
    for f in range(20):
        raw = dets[f][0]
        b = t.boxes[f]
        assert b[0] <= raw.x0 and b[1] <= raw.y0 and b[2] >= raw.x1 and b[3] >= raw.y1


def test_tracker_separates_two_faces():
    dets = {f: [_det(f, 100), _det(f, 800)] for f in range(30)}
    assert len(track(dets, 30, 30, 1280, 720)) == 2


def test_single_weak_blip_dropped_single_confident_kept():
    weak = track({5: [_det(5, 100, 0.42)]}, 30, 30, 1280, 720)
    strong = track({5: [_det(5, 100, 0.8)]}, 30, 30, 1280, 720)
    assert weak == [] and len(strong) == 1


def test_keyframe_interpolation():
    kf = interpolate_keyframes({0: (0, 0, 10, 10), 10: (100, 0, 110, 10)}, 20)
    assert kf[5] == (50, 0, 60, 10) and kf[10] == (100, 0, 110, 10)


def test_track_roundtrip():
    t = Track(3, "face", enabled=False)
    t.boxes = {1: (1, 2, 3, 4), 2: (2, 3, 4, 5)}
    t2 = Track.from_dict(t.to_dict())
    assert t2.boxes == t.boxes and not t2.enabled and t2.first == 1 and t2.last == 2


@pytest.mark.parametrize("effect", ["bleep", "mute", "noise"])
def test_audio_redact_samples(effect):
    sr = 16000
    data = (np.random.default_rng(1).random((sr * 2, 2)) - 0.5).astype(np.float32)
    out = redact_samples(data, sr, [(0.5, 1.0)], effect)
    seg, orig = out[int(0.5 * sr) + 200:int(1.0 * sr) - 200], data[int(0.5 * sr) + 200:int(1.0 * sr) - 200]
    assert not np.allclose(seg, orig)
    if effect == "mute":
        assert np.abs(seg).max() == 0
    assert np.allclose(out[:int(0.4 * sr)], data[:int(0.4 * sr)])


def test_merge_ranges():
    assert merge_ranges([(1, 2), (1.9, 3), (5, 6), (6.02, 7)]) == [(1, 3), (5, 7)]


# ---- vision (models) ------------------------------------------------------------------------------
@pytest.mark.vision
@pytest.mark.parametrize("img,min_faces", [("zidane.jpg", 2), ("bus.jpg", 3), ("lena.jpg", 1), ("messi5.jpg", 1)])
def test_faces_found_and_redacted(tmp_path, img, min_faces):
    from obscura.redact.image import ImageDocument
    d = ImageDocument(FIX / "images" / img)
    dets = d.analyze({"face", "head"}, text=False)
    assert sum(1 for x in dets if x.entity == "FACE") >= min_faces
    rep = d.apply(dets, tmp_path / "o.jpg", effect="blur")
    assert rep["verification"]["passed"], rep


@pytest.mark.vision
def test_image_metadata_stripped(tmp_path):
    from PIL.ExifTags import Base
    from obscura.redact.image import ImageDocument
    src = tmp_path / "gps.jpg"
    im = Image.open(FIX / "images" / "zidane.jpg")
    exif = Image.Exif()
    exif[Base.Artist] = "Officer Daniel Ruiz"
    exif[Base.ImageDescription] = "Suspect Maria Delgado at 4417 Oakridge Dr"
    im.save(src, exif=exif.tobytes())
    d = ImageDocument(src)
    out = tmp_path / "o.jpg"
    d.apply(d.analyze({"face"}, text=False), out)
    data = out.read_bytes()
    assert b"Ruiz" not in data and b"Delgado" not in data and not Image.open(out).getexif()


@pytest.mark.vision
def test_text_in_photo_redacted(tmp_path):
    from obscura.redact import ocr
    from obscura.redact.image import ImageDocument
    im = Image.new("RGB", (1400, 500), "white")
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 46)
    except OSError:
        font = ImageFont.load_default()
    dr.text((60, 80), "Patient: Maria Delgado", fill="black", font=font)
    dr.text((60, 180), "SSN: 523-71-9921", fill="black", font=font)
    dr.text((60, 280), "Diagnosis: lumbar strain", fill="black", font=font)
    src = tmp_path / "note.png"
    im.save(src)
    d = ImageDocument(src)
    dets = d.analyze(set(), text=True)
    out = tmp_path / "o.png"
    d.apply(dets, out)
    words = " ".join(w.text for w in ocr.ocr_image(Image.open(out)))
    assert "523-71-9921" not in words and "Delgado" not in words and "lumbar" in words


@pytest.mark.vision
def test_image_verifier_catches_unredacted(tmp_path):
    from obscura.redact.image import ImageDocument
    d = ImageDocument(FIX / "images" / "zidane.jpg")
    rep = d.apply([], tmp_path / "o.jpg")
    assert not rep["verification"]["passed"]


@pytest.mark.vision
def test_video_end_to_end(tmp_path):
    from obscura.redact.video import FFMPEG, VideoDocument, probe
    v = VideoDocument(FIX / "media" / "moving_faces.mp4")
    tracks = v.analyze({"face", "head", "license_plate"}, mode="balanced")
    assert len([t for t in tracks if t.label == "face"]) >= 2
    out = tmp_path / "o.mp4"
    rep = v.render(out, effect="blur")
    assert rep["verification"]["passed"], rep["verification"]
    assert probe(out).frames >= 140 and probe(out).has_audio
    meta = subprocess.run([FFMPEG, "-i", str(out)], capture_output=True, text=True).stderr
    assert "Bodycam" not in meta and "GPS" not in meta


@pytest.mark.vision
def test_video_keep_visible_track_not_flagged(tmp_path):
    from obscura.redact.video import VideoDocument
    v = VideoDocument(FIX / "media" / "moving_faces.mp4")
    v.analyze({"face"}, mode="fast")
    v.tracks[0].enabled = False  # e.g. the officer stays visible by decision
    rep = v.render(tmp_path / "o.mp4")
    assert rep["verification"]["passed"], rep["verification"]


@pytest.mark.vision
def test_manual_tracks(tmp_path):
    from obscura.redact.video import VideoDocument
    v = VideoDocument(FIX / "media" / "moving_faces.mp4")
    t1 = v.add_manual_track(10, (100, 100, 300, 300), mode="static", end_frame=40)
    t2 = v.add_manual_track(0, (500, 50, 700, 300), mode="track", end_frame=60)
    t3 = v.add_manual_track(0, (0, 0, 10, 10), mode="keyframes", keyframes={"0": [0, 0, 10, 10], "20": [100, 0, 110, 10]})
    assert min(t1.boxes) == 10 and max(t1.boxes) == 40 and len(t2.boxes) > 30 and t3.boxes[10] == (50, 0, 60, 10)


# ---- speech ------------------------------------------------------------------------------------
@pytest.mark.audio
def test_audio_bleep_and_reverify(tmp_path):
    from obscura.detection.text.engine import AnalyzeOptions
    from obscura.redact.audio import AudioDocument
    a = AudioDocument(FIX / "media" / "speech.aiff")
    dets = a.analyze(AnalyzeOptions(use_spacy=False, use_gliner=False))
    ents = {d.entity for d in dets if d.selected}
    assert {"SSN", "PHONE", "ADDRESS"} <= ents, ents
    rep = a.apply(dets, tmp_path / "o.wav")
    assert rep["verification"]["passed"], rep
    srt = a.captions(dets)
    assert "[REDACTED]" in srt and "0187" not in srt


@pytest.mark.audio
@pytest.mark.parametrize("phrase,entity", [
    ("My credit card number is four one one one, one one one one, one one one one, one one one one.", "CREDIT_CARD"),
    ("You can reach me at area code five one two, five five five, zero one four four.", "PHONE"),
    ("My date of birth is January fifteenth, nineteen eighty.", "DATE_OF_BIRTH"),
    ("The routing number is zero two one, zero zero zero, zero two one.", "ROUTING_NUMBER"),
])
def test_spoken_pii(tmp_path, phrase, entity):
    from obscura.detection.text.engine import AnalyzeOptions
    from obscura.redact.audio import AudioDocument
    wav = tmp_path / "s.aiff"
    subprocess.run(["say", "-o", str(wav), phrase], check=True)
    a = AudioDocument(wav)
    a.transcribe("small.en")
    dets = a.analyze(AnalyzeOptions(use_spacy=False, use_gliner=False))
    assert any(d.entity == entity for d in dets) or any(d.selected for d in dets), (a.transcript.text, [(d.entity, d.text) for d in dets])
