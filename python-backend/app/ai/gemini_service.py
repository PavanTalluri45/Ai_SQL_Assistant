import collections
import logging
import os
import re
import threading
import time
from dotenv import load_dotenv
from google import genai

# Load environment variables
load_dotenv()

# Read API Key
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env")

# Create Gemini Client
client = genai.Client(api_key=api_key)

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Thread-safe sliding-window rate limiter for Gemini API calls.
    Enforces RPM (Requests Per Minute) limits, active cooldowns, and minimum spacing
    between concurrent calls to prevent HTTP 429 quota exhaustion.
    """

    def __init__(
        self,
        rpm: int = 15,
        window_seconds: float = 60.0,
        min_interval: float = 0.5,
    ):
        self.rpm = rpm
        self.window_seconds = window_seconds
        self.min_interval = min_interval
        self.lock = threading.Lock()
        self.request_timestamps = collections.deque()
        self.last_request_time = 0.0
        self.pause_until = 0.0

    def pause_all(self, duration_seconds: float) -> None:
        """Globally pause all outgoing requests until cooldown expires."""
        with self.lock:
            target = time.monotonic() + duration_seconds
            if target > self.pause_until:
                self.pause_until = target

    def acquire(self) -> None:
        """
        Block until an API call slot is available according to RPM limits,
        active cooldowns, and minimum inter-request intervals.
        """
        while True:
            sleep_needed = 0.0
            with self.lock:
                now = time.monotonic()

                # 1. Check if global cooldown is active (e.g. from an upstream 429)
                if now < self.pause_until:
                    sleep_needed = max(sleep_needed, self.pause_until - now)

                # 2. Check minimum interval between consecutive requests
                elapsed = now - self.last_request_time
                if elapsed < self.min_interval:
                    sleep_needed = max(sleep_needed, self.min_interval - elapsed)

                # 3. Check sliding-window RPM limit
                while self.request_timestamps and (now - self.request_timestamps[0] >= self.window_seconds):
                    self.request_timestamps.popleft()

                if len(self.request_timestamps) >= self.rpm:
                    oldest = self.request_timestamps[0]
                    window_wait = (oldest + self.window_seconds) - now + 0.1
                    sleep_needed = max(sleep_needed, window_wait)

                # If no wait needed, reserve slot
                if sleep_needed <= 0.0:
                    reserve_time = time.monotonic()
                    self.request_timestamps.append(reserve_time)
                    self.last_request_time = reserve_time
                    return

            # Sleep outside the lock so other threads can inspect state
            if sleep_needed > 0.0:
                logger.info(
                    "RateLimiter: waiting %.2fs to respect %d RPM limit / cooldown...",
                    sleep_needed,
                    self.rpm,
                )
                time.sleep(sleep_needed)


# Initialize global rate limiter with configurable RPM
_RPM_LIMIT = int(os.getenv("GEMINI_RPM_LIMIT", "15"))
rate_limiter = RateLimiter(rpm=_RPM_LIMIT, window_seconds=60.0, min_interval=0.5)


def generate_response(prompt: str, max_retries: int = 5) -> str:
    """
    Sends a prompt to Gemini and returns the generated text.
    Includes proactive rate limiting and automated retry handling with backoff for rate limits (HTTP 429).

    Args:
        prompt (str): Prompt sent to Gemini.
        max_retries (int): Maximum number of retries upon hitting rate limits.

    Returns:
        str: Gemini response.
    """
    delay = 2.0
    for attempt in range(max_retries):
        # Proactively acquire a slot before sending request
        rate_limiter.acquire()
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt
            )
            return response.text
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()) and attempt < max_retries - 1:
                # Extract suggested retry delay if present in error message
                match = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
                if not match:
                    match = re.search(r"retryDelay':\s*'(\d+)s'", err_str)
                sleep_time = float(match.group(1)) + 1.0 if match else delay
                logger.warning(f"Rate limit hit (429). Pausing all requests for {sleep_time:.1f}s (attempt {attempt + 1}/{max_retries})...")
                rate_limiter.pause_all(sleep_time)
                time.sleep(sleep_time)
                delay *= 2
            else:
                logger.error(f"Gemini API error on attempt {attempt + 1}: {e}")
                raise e
