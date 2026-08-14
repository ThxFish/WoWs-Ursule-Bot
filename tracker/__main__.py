import uvicorn

from .config import config

uvicorn.run("tracker.app:app", host=config.host, port=config.port, workers=1)

