"""Entrypoint: python -m cos.webapp"""

from __future__ import annotations

import logging

import uvicorn

from cos.webapp.app import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
