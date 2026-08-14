from dataclasses import dataclass


@dataclass(frozen=True)
class BotReply:
    text: str
    image: bytes | None = None
    image_alt: str | None = None

    def truncated_text(self, limit: int) -> str:
        return self.text[:limit]
