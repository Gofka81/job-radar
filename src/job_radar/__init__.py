"""job-hunt: deterministic UK job-discovery pipeline."""

import logging

__version__ = "0.1.0"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure timestamped logging for the whole app. Idempotent."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    # Quiet the per-request firehose from HTTP libs — we log our own summaries.
    for noisy in ("httpx", "httpcore", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
