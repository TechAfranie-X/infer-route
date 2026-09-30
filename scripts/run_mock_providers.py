"""Start the configured mock model processes for local development.

Docker Compose is the supported demo. This script is the same processes without Compose.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    providers = [
        ("provider-a", "8081", "150", "0.02"),
        ("provider-b", "8082", "300", "0.01"),
        ("provider-c", "8083", "100", "0.10"),
    ]
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for provider_id, port, latency_ms, failure_rate in providers:
            env = os.environ.copy()
            env.update(
                {
                    "MOCK_PROVIDER_ID": provider_id,
                    "MOCK_PORT": port,
                    "MOCK_LATENCY_MS": latency_ms,
                    "MOCK_FAILURE_RATE": failure_rate,
                }
            )
            processes.append(subprocess.Popen([sys.executable, "-m", "app.mock"], env=env))
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        for process in processes:
            process.terminate()


if __name__ == "__main__":
    main()
