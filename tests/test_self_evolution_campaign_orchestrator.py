from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

from core.web.services import self_evolution_autonomous_loop_orchestrator as module


def test_campaign_start_is_nonblocking_deduplicated_and_deadline_requests_exact_stop(monkeypatch):
    entered, release = Event(), Event()
    calls, timers = [], []
    class Timer:
        def __init__(self, delay, callback, args):
            self.callback, self.args = callback, args
            self.cancelled = False
            timers.append(self)
        def start(self):
            pass
        def cancel(self):
            self.cancelled = True
    monkeypatch.setattr(module.threading, "Timer", Timer)
    def run(value):
        calls.append(("run", value))
        entered.set()
        assert release.wait(3)
    campaign = SimpleNamespace(
        queue=lambda body: {"runId": "campaign-1", "status": "queued",
                            "deadline": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()},
        run=run, check_deadline=lambda value: calls.append(("deadline", value)),
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        owner = module.SelfEvolutionAutonomousLoopOrchestrator(service=None, executor=executor,
                                                              campaign_service=campaign)
        owner.start_campaign({})
        try:
            assert entered.wait(3)
            owner.start_campaign({})
            assert len(timers) == 1
            timers[0].callback(*timers[0].args)
            assert calls == [("run", "campaign-1"), ("deadline", "campaign-1")]
        finally:
            release.set()
    assert timers[0].cancelled
