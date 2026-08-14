import uvicorn

from .core.config import config


def main() -> None:
    uvicorn.run("ursule_bot.application:app", host=config.host, port=config.port, workers=1)


if __name__ == "__main__":
    main()
