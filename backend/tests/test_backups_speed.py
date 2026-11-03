"""Administration > Backups and /health/full asked our OSRM for a route on every load (about 1.3 s
on the test server): the answer is kept 60 s, a failure only 10 s."""

import urllib.request

from app.ops import service


class _Answer:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_osrm_check_is_kept_a_minute_and_a_failure_ten_seconds(monkeypatch):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(service, "_OSRM_SEEN", {"at": 0.0, "result": None})

    def ok(url, timeout):
        calls.append(url)
        return _Answer()

    monkeypatch.setattr(urllib.request, "urlopen", ok)
    assert service._osrm() == ("ok", None) and service._osrm() == ("ok", None) and len(calls) == 1
    clock[0] += 61
    assert service._osrm() == ("ok", None) and len(calls) == 2

    def down(url, timeout):
        calls.append(url)
        raise TimeoutError

    monkeypatch.setattr(urllib.request, "urlopen", down)
    clock[0] += 61
    assert service._osrm() == ("error", "TimeoutError") and len(calls) == 3
    clock[0] += 5
    assert service._osrm() == ("error", "TimeoutError") and len(calls) == 3
    clock[0] += 6
    service._osrm()
    assert len(calls) == 4  # a failure is asked again after 10 s
