import threading
import time
from app.ai.gemini_service import RateLimiter


def test_rate_limiter_min_interval():
    limiter = RateLimiter(rpm=60, window_seconds=60.0, min_interval=0.1)
    t0 = time.monotonic()
    limiter.acquire()
    limiter.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.09, f"Expected elapsed >= 0.09s, got {elapsed:.3f}s"


def test_rate_limiter_concurrency():
    limiter2 = RateLimiter(rpm=20, window_seconds=60.0, min_interval=0.02)
    acquired_times = []
    lock = threading.Lock()

    def worker():
        limiter2.acquire()
        with lock:
            acquired_times.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(acquired_times) == 5
    acquired_times.sort()
    for i in range(1, len(acquired_times)):
        spacing = acquired_times[i] - acquired_times[i - 1]
        assert spacing >= 0.015, f"Spacing {spacing} < 0.015"


def test_rate_limiter_pause_all():
    limiter3 = RateLimiter(rpm=60, window_seconds=60.0, min_interval=0.01)
    limiter3.pause_all(0.2)
    t0 = time.monotonic()
    limiter3.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.19, f"Pause elapsed {elapsed} < 0.19"
