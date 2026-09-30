"""Run one mock model endpoint: ``python -m app.mock``."""

import uvicorn

from app.mock.server import create_mock_app
from app.mock.settings import MockSettings


def main() -> None:
    settings = MockSettings()
    uvicorn.run(
        create_mock_app(settings),
        host=settings.host,
        port=settings.mock_port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
