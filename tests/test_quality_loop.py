"""Boucle de contrôle qualité, avec des modèles simulés (rapide, déterministe, sans puce graphique)."""
from PIL import Image

from komian.checks import loop_checks
from komian.quality_loop import create, finalize, plan_action
from komian.saliency import face_geometry
from komian.verifier import parse_box

GOOD_FACE = {"ok": True, "score": 0.8, "width": 100, "sharpness": 300, "confidence": 0.93, "problems": []}
BAD_FACE = {"ok": False, "score": 0.3, "width": 40, "sharpness": 50, "confidence": 0.65,
            "problems": ["visage trop petit"]}


class FakeBackend:
    """Images unies numérotées ; réponses du vérificateur jouées selon un scénario."""

    def __init__(self, answers, hand=(100, 200, 160, 260), bare=()):
        self.answers, self.hand, self.calls, self.bare = list(answers), hand, [], list(bare)

    def generate(self, prompt, seed):
        self.calls.append(("generate", seed))
        return Image.new("RGB", (512, 512), (seed % 256, 0, 0))

    def action_done(self, question, image):
        self.calls.append(("check", question))
        return self.answers.pop(0)

    def is_bare(self, image):
        self.calls.append(("bare", None))
        return self.bare.pop(0) if self.bare else False

    def locate_hand(self, obj, image):
        self.calls.append(("locate", obj))
        return self.hand

    def add_object(self, image, mask, prompt, seed):
        self.calls.append(("add", seed))
        return Image.new("RGB", image.size, (0, 255, 0))

    def refine(self, image, prompt, seed, strength):
        self.calls.append(("refine", strength))
        return image


def kinds(backend):
    return [c[0] for c in backend.calls]


DRILL = "Black man wearing a red polo shirt, using a power drill on a wall, medium shot, looking at the camera"


def test_action_template_puts_gesture_first_and_drops_camera_gaze():
    plan = plan_action(DRILL)
    assert plan.object == "power drill" and plan.holdable
    assert plan.prompt.startswith("holding a cordless power drill")
    assert "looking at the camera" not in plan.prompt
    assert plan.question.startswith("Is the person drilling")
    assert plan_action("bright living room, warm light").question is None


def test_realistic_image_wording_becomes_a_photo_style():
    plan = plan_action("A realistic image of a young man in blue clothing, holding a hammer in hand")
    assert "realistic image" not in plan.prompt.lower() and "candid photo of a young man" in plan.prompt


def test_person_without_clothing_words_is_dressed():
    from komian.quality_loop import DRESSED
    assert DRESSED in plan_action("portrait of an older African man in a workshop").prompt
    assert DRESSED not in plan_action("older man wearing a red apron in a workshop").prompt
    assert DRESSED not in plan_action("bright empty living room").prompt


def test_bare_candidate_is_rejected_and_never_preferred():
    backend = FakeBackend([True], bare=[True, False])
    _, report = create(DRILL, 10, backend, face_fn=lambda img: GOOD_FACE)
    assert kinds(backend) == ["generate", "bare", "generate", "bare", "check"]  # pas de question d'action au 1er
    assert report["seed"] == 11 and report["clothed"]


def test_first_good_candidate_stops_the_loop():
    backend = FakeBackend([True])
    _, report = create(DRILL, 10, backend, face_fn=lambda img: GOOD_FACE)
    assert kinds(backend) == ["generate", "bare", "check"]
    assert report["action_verified"] and report["candidates"] == 1 and report["clothed"] and not report["object_added"]


def test_object_is_added_in_the_hand_when_no_candidate_does_the_action():
    backend = FakeBackend([False, False, False, False, True])
    image, report = create(DRILL, 10, backend, face_fn=lambda img: GOOD_FACE)
    assert kinds(backend) == ["generate", "bare", "check"] * 3 + ["locate", "add", "check", "add", "check"]
    assert report["object_added"] and report["action_verified"]
    assert image.getpixel((0, 0)) == (0, 255, 0)


def test_action_not_found_is_reported_without_looping_forever():
    backend = FakeBackend([False] * 6)
    _, report = create(DRILL, 10, backend, face_fn=lambda img: GOOD_FACE)
    assert report["action_verified"] is False and not report["object_added"]
    assert kinds(backend).count("add") == 2


def test_bad_face_is_not_checked_and_the_best_face_is_kept():
    faces = iter([BAD_FACE, GOOD_FACE])
    backend = FakeBackend([True])
    _, report = create(DRILL, 10, backend, face_fn=lambda img: next(faces))
    # visage raté : tenue contrôlée (il pourrait être retenu en dernier recours), pas de question sur l'action
    assert kinds(backend) == ["generate", "bare", "generate", "bare", "check"]
    assert report["face"] == GOOD_FACE and report["seed"] == 11


def test_budget_stops_new_candidates():
    ticks = iter(range(0, 1000, 85))  # chaque lecture de l'horloge avance de 85 s : plus de place après la 1re
    backend = FakeBackend([False] * 6)
    _, report = create(DRILL, 10, backend, face_fn=lambda img: GOOD_FACE, budget_s=90, clock=lambda: next(ticks))
    assert report["candidates"] == 1 and "add" not in kinds(backend)


def test_scene_without_requested_action_only_checks_the_face():
    backend = FakeBackend([])
    _, report = create("modern bright kitchen, warm light", 10, backend, face_fn=lambda img: None)
    assert kinds(backend) == ["generate"] and report["action_verified"] is None


def test_quality_pass_rechecks_the_action():
    backend = FakeBackend([False])
    report = {"prompt": "p", "question": "Is the person drilling?"}
    _, final = finalize(Image.new("RGB", (512, 512)), report, 1, backend, strength=0.4,
                        face_fn=lambda img: GOOD_FACE)
    assert kinds(backend) == ["refine", "bare", "check"] and final["action_verified"] is False


def test_face_geometry_flags_misplaced_features():
    good = [(40, 50), (80, 50), (60, 70), (45, 90), (75, 90)]
    assert all(face_geometry(100, good).values())
    nose_aside = [(40, 50), (80, 50), (120, 70), (45, 90), (75, 90)]
    assert not face_geometry(100, nose_aside)["nez entre les yeux"]
    mouth_above = [(40, 50), (80, 50), (60, 70), (45, 30), (75, 30)]
    assert not face_geometry(100, mouth_above)["yeux, nez et bouche dans l'ordre"]


def test_verifier_box_is_read_on_a_0_1000_scale():
    assert parse_box('{"bbox_2d": [100, 500, 300, 750]}', (512, 512)) == [51.2, 256.0, 153.6, 384.0]
    assert parse_box("no box here", (512, 512)) is None


def test_bare_person_blocks_approval():
    results = {r.name: r for r in loop_checks({"clothed": True, "final": {"clothed": False}})}
    assert results["Tenue"].status == "anomalie"


def test_loop_checks_use_the_final_version_when_present():
    loop = {"question": "Is the person drilling?", "object": "power drill", "action_verified": True,
            "face": GOOD_FACE, "final": {"action_verified": False, "face": BAD_FACE}}
    results = {r.name: r for r in loop_checks(loop)}
    assert results["Action demandée"].status == "non_concluant"
    assert "relancez ou utilisez une photo" in results["Action demandée"].detail
    assert results["Visage"].status == "non_concluant" and "trop petit" in results["Visage"].detail
