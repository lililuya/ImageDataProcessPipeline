import copy

import pytest

from idp.evaluation.audit import estimate, sample_frame


def frame():
    return ([{"sample_id": f"common-{i}", "stratum": "common"} for i in range(900)] +
            [{"sample_id": f"rare-{i}", "stratum": "rare"} for i in range(100)])


def test_weighted_oversampling_and_frame_order_invariance():
    plan = sample_frame(frame(), {"common": 10, "rare": 90}, 42)
    assert plan == sample_frame(list(reversed(frame())), {"rare": 90, "common": 10}, 42)
    for row in plan["selected"]:
        row["label"] = int(row["stratum"] == "rare")
        row["reviewer"] = "synthetic-gold"
    result = estimate(plan)
    assert sum(r["label"] for r in plan["selected"]) / 100 == .9
    assert result["estimate"] == pytest.approx(.1)
    assert result["interval"][0] <= .1 <= result["interval"][1]
    assert {r["inclusion_probability"] for r in plan["selected"]} == {10 / 900, .9}


def test_census_has_no_sampling_error():
    plan = sample_frame(frame(), {"common": 900, "rare": 100}, 42)
    for row in plan["selected"]:
        row.update(label=int(row["stratum"] == "rare"), reviewer="gold")
    assert estimate(plan)["interval"] == pytest.approx([.1, .1])


def test_incomplete_unknown_and_tampered_reviews_rejected():
    plan = sample_frame(frame(), {"common": 2, "rare": 2}, 42)
    with pytest.raises(ValueError, match="ALL_SELECTED"):
        estimate(plan)
    for r in plan["selected"]:
        r.update(label=0, reviewer="gold")
    for mutate in (lambda p: p["selected"].pop(),
                   lambda p: p["selected"][0].update(inclusion_probability=.5),
                   lambda p: p["selected"].append(p["selected"][0])):
        bad = copy.deepcopy(plan)
        mutate(bad)
        with pytest.raises(ValueError):
            estimate(bad)
    with pytest.raises(ValueError, match="EVERY_STRATUM"):
        sample_frame(frame(), {"rare": 1}, 0)
    with pytest.raises(ValueError, match="DUPLICATE"):
        sample_frame(frame() + frame()[:1], {"common": 1, "rare": 1}, 0)
