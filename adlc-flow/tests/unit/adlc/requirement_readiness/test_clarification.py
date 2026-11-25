import pytest

from langflow.adlc.requirement_readiness.clarification import validate_round_response


def test_answer_is_not_confirmation_and_unknown_ids_are_rejected():
    row = {"id": "round", "kind": "frontier", "questions": [{"id": "q"}]}
    assert validate_round_response(row, {"answers": {"q": "actual answer"}, "confirmed": False})["confirmed"] is False
    for response in ({"answers": {"other": "yes"}, "confirmed": False}, {"answers": {"q": "yes"}, "confirmed": True}):
        with pytest.raises(ValueError, match="READINESS_ANSWER_INVALID"):
            validate_round_response(row, response)
    assert (
        validate_round_response({"kind": "confirmation", "questions": []}, {"answers": {}, "confirmed": True})[
            "confirmed"
        ]
        is True
    )
