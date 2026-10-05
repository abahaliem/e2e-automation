from qa_agent.agent.loop_detect import LoopDetector


def test_warn_then_block():
    d = LoopDetector()
    assert [d.record("fp", "click", "#a") for _ in range(4)] == ["ok", "ok", "warn", "block"]


def test_different_targets_counted_separately():
    d = LoopDetector()
    for _ in range(2):
        d.record("fp", "click", "#a")
    assert d.record("fp", "click", "#b") == "ok"
    assert d.record("fp2", "click", "#a") == "ok"
