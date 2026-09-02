# tests/test_state_machine.py
import time
from hand_detector import HandStateMachine

def test_open_then_fist_triggers():
    sm = HandStateMachine(max_transition_time=1.5, cooldown=2.0)
    t0 = time.time()
    triggered, info = sm.feed("OPEN", ts=t0)
    assert triggered is False
    # within transition time
    triggered2, info2 = sm.feed("FIST", ts=t0 + 1.0)
    assert triggered2 is True
    # after triggering, immediate second FIST should be blocked by cooldown
    triggered3, info3 = sm.feed("FIST", ts=t0 + 1.1)
    assert triggered3 is False
    assert info3.get("reason") == "cooldown" or info3.get("state") == "FIST"

def test_fist_without_open_doesnt_trigger():
    sm = HandStateMachine(max_transition_time=1.0, cooldown=1.0)
    t0 = time.time()
    triggered, info = sm.feed("FIST", ts=t0)
    assert triggered is False
    assert info.get("reason") == "no_recent_open"
