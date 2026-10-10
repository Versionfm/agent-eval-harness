"""Canonical synthetic acceptance checks for the pinned ML Tutor call path."""

import copy
import json
import platform
import sys

from app.source import retrieve
from app.tutor import answer


TITLE_ID = "synthetic.weight-decay"
DECOY_ID = "synthetic.unrelated"


def title_sections():
    return [
        {
            "id": DECOY_ID,
            "title": "Graph Output",
            "url": "https://example.invalid/graph-output",
            "text": "This synthetic section discusses tensor logging only.",
        },
        {
            "id": TITLE_ID,
            "title": "Weight Decay",
            "url": "https://example.invalid/weight-decay",
            "text": "A synthetic passage whose body omits the queried words.",
        },
    ]


def body_sections():
    return [
        {
            "id": "synthetic.optimizer-state",
            "title": "Optimizer State",
            "url": "https://example.invalid/optimizer-state",
            "text": "Momentum buffers preserve earlier update directions.",
        },
        {
            "id": "synthetic.gradient-descent",
            "title": "Parameter Updates",
            "url": "https://example.invalid/parameter-updates",
            "text": "Gradient descent subtracts a scaled gradient from the weights.",
        },
    ]


class FakeChat:
    def __init__(self):
        self.calls = []

    def __call__(self, system, messages):
        self.calls.append((system, messages))
        return "Synthetic answer [synthetic.weight-decay]."


def check_title_retrieval():
    selected = retrieve("WHAT IS WEIGHT DECAY?", title_sections(), k=1)
    assert selected[0]["id"] == TITLE_ID, (
        f"retrieval selected {selected[0]['id']!r} before the title-matched passage"
    )


def check_title_context():
    chat = FakeChat()
    answer("WHAT IS WEIGHT DECAY?", chat=chat, sections=title_sections(),
           prompt="Synthetic tutor rules", k=1)
    system, _ = chat.calls[0]
    assert f'id="{TITLE_ID}"' in system, "tutor context omitted the title-matched passage"
    assert f'id="{DECOY_ID}"' not in system, "top-1 tutor context retained the unrelated passage"


def check_body_relevance():
    selected = retrieve("How does gradient descent update weights?", body_sections(), k=1)
    assert selected[0]["id"] == "synthetic.gradient-descent", (
        "body-text match did not rank first"
    )


def check_case_normalization():
    selected = retrieve("WHAT DOES GRADIENT DESCENT DO?", body_sections(), k=1)
    assert selected[0]["id"] == "synthetic.gradient-descent", (
        "uppercase query did not match lowercase body terms"
    )


def check_top_k_limit():
    sections = body_sections() + [
        {
            "id": "synthetic.loss",
            "title": "Loss",
            "url": "https://example.invalid/loss",
            "text": "A loss measures prediction error.",
        }
    ]
    selected = retrieve("gradient descent", sections, k=2)
    assert len(selected) == 2, f"k=2 returned {len(selected)} sections"


def check_input_immutable():
    sections = title_sections()
    before = copy.deepcopy(sections)
    retrieve("WHAT IS WEIGHT DECAY?", sections, k=1)
    assert sections == before, "retrieval changed its input sections"


def check_full_context_bypass():
    sections = title_sections() + body_sections()
    chat = FakeChat()
    answer("WHAT IS WEIGHT DECAY?", chat=chat, sections=sections,
           prompt="Synthetic tutor rules", retrieval="full", k=1)
    system, _ = chat.calls[0]
    omitted = [section["id"] for section in sections if f'id="{section["id"]}"' not in system]
    assert not omitted, f"full-context mode omitted sections: {omitted!r}"


def check_history_mode():
    history = [
        {"role": "user", "content": "Prior synthetic question"},
        {"role": "assistant", "content": "Prior synthetic answer"},
    ]
    chat = FakeChat()
    answer("Quiz me", chat=chat, sections=body_sections(), prompt="RULES",
           history=history, mode="quiz")
    system, messages = chat.calls[0]
    assert "Mode: quiz" in system, "quiz mode was lost"
    assert messages[:len(history)] == history, "conversation history was changed"
    assert messages[-1] == {"role": "user", "content": "Quiz me"}, "current question was lost"


def check_input_order_independence():
    decoy, target = title_sections()
    for ordered in ([decoy, target], [target, decoy]):
        selected = retrieve("WHAT IS WEIGHT DECAY?", ordered, k=1)
        assert selected[0]["id"] == TITLE_ID, (
            f"selected {selected[0]['id']!r} for input order "
            f"{[section['id'] for section in ordered]!r}"
        )


CHECKS = {
    "title_retrieval": check_title_retrieval,
    "title_context": check_title_context,
    "body_relevance": check_body_relevance,
    "case_normalization": check_case_normalization,
    "top_k_limit": check_top_k_limit,
    "input_immutable": check_input_immutable,
    "full_context_bypass": check_full_context_bypass,
    "history_mode": check_history_mode,
    "input_order_independence": check_input_order_independence,
}


def main():
    checks = {}
    messages = {}
    unexpected_errors = {}
    for check_id, check in CHECKS.items():
        try:
            check()
        except AssertionError as exc:
            checks[check_id] = False
            messages[check_id] = str(exc)
        except Exception as exc:  # An evaluator/runtime problem is not a task failure.
            unexpected_errors[check_id] = f"{type(exc).__name__}: {exc}"
        else:
            checks[check_id] = True
            messages[check_id] = "passed"

    status = "error" if unexpected_errors else "completed"
    print(json.dumps({
        "status": status,
        "python_version": platform.python_version(),
        "checks": checks,
        "messages": messages,
        "unexpected_errors": unexpected_errors,
    }, sort_keys=True))
    return 2 if unexpected_errors else 0


if __name__ == "__main__":
    sys.exit(main())
