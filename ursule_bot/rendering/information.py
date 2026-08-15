from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO

from PIL import Image, ImageDraw, ImageOps

from .flat import FlatCanvas


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    published_at: date | datetime | str
    description: str = ""
    tags: tuple[str, ...] = ()
    tag_color: str = "#147D92"
    url: str = ""
    thumbnail: bytes | None = None


class InformationRenderer:
    """Two-column news board matching the two official WoWS card styles."""

    width = 1600
    top = 250
    margin = 70
    column_gap = 30
    row_gap = 24
    card_width = 715
    card_height = 640
    image_height = 386
    bottom = 105

    def render(self, items: list[NewsItem] | tuple[NewsItem, ...]) -> bytes:
        visible = list(items[:8])
        rows = max(1, (len(visible) + 1) // 2)
        height = self.top + rows * self.card_height + max(0, rows - 1) * self.row_gap + self.bottom
        card = FlatCanvas(self.width, height)
        card.image.paste("#151A20", (0, 0, self.width, height))
        card.ink = "#F4F7FA"
        card.ink_muted = "#A9B5C1"
        card.divider = "#35414C"
        self._header(card, len(visible))
        if visible:
            for index, item in enumerate(visible):
                column, row = index % 2, index // 2
                x = self.margin + column * (self.card_width + self.column_gap)
                y = self.top + row * (self.card_height + self.row_gap)
                if item.source == "开发者博客":
                    self._devblog_card(card, item, x, y)
                else:
                    self._official_card(card, item, x, y)
        else:
            self._empty(card)
        card.footer("URSULE BOT  ·  信息中心")
        return card.png()

    @staticmethod
    def _header(card: FlatCanvas, count: int) -> None:
        card.text("INFORMATION CENTER", (70, 62), 24, fill="#73D8E1")
        card.text("信息中心", (70, 105), 56)
        card.text("官网新闻与开发者博客", (70, 178), 27, fill=card.ink_muted)
        card.pill(f"近 7 日 · {count} 条", (1310, 98), fill="#243C48", ink="#9DEAF0", size=23)

    def _official_card(self, card: FlatCanvas, item: NewsItem, x: int, y: int) -> None:
        bottom = y + self.card_height
        card.draw.rectangle((x, y, x + self.card_width, bottom), fill="#22394A", outline="#355064", width=2)
        self._thumbnail(card, item, (x + 2, y + 2, x + self.card_width - 2, y + self.image_height), radius=0)
        tag = item.tags[0] if item.tags else "官网新闻"
        self._label(card, tag, x + 30, y + 28, item.tag_color, "#FFFFFF", 21)
        self._label(card, self._official_date(item.published_at), x + 30, y + self.image_height - 70, "#1A2229", "#FFFFFF", 21)
        body_x = x + 30
        text_y = y + self.image_height + 34
        for line in card.wrapped_lines(item.title, self.card_width - 60, 31, 2):
            card.text(line, (body_x, text_y), 31, fill="#A9EDF1")
            text_y += 43
        if item.description:
            description_y = max(text_y + 8, y + self.image_height + 105)
            for line in card.wrapped_lines(item.description, self.card_width - 60, 24, 3):
                card.text(line, (body_x, description_y), 24, fill="#E0E7ED")
                description_y += 34

    def _devblog_card(self, card: FlatCanvas, item: NewsItem, x: int, y: int) -> None:
        bottom = y + self.card_height
        card.draw.rounded_rectangle((x, y, x + self.card_width, bottom), radius=8, fill="#202020")
        self._thumbnail(card, item, (x, y, x + self.card_width, y + self.image_height), radius=8)
        self._devblog_tags(card, item.tags, x + 28, y + 28, self.card_width - 56)
        body_x = x + 30
        text_y = y + self.image_height + 32
        for line in card.wrapped_lines(item.title, self.card_width - 60, 30, 2):
            card.text(line, (body_x, text_y), 30, fill="#FFFFFF")
            text_y += 42
        if item.description:
            description_y = y + self.image_height + 132
            for line in card.wrapped_lines(item.description, self.card_width - 60, 23, 2):
                card.text(line, (body_x, description_y), 23, fill="#D8D8D8")
                description_y += 32
        date_text, time_text = self._devblog_date(item.published_at)
        card.text(date_text, (body_x, bottom - 31), 18, fill="#FFFFFF", anchor="ls")
        date_width = card.draw.textlength(date_text, font=card.font(18))
        divider_x = body_x + int(date_width) + 18
        card.draw.line((divider_x, bottom - 48, divider_x, bottom - 24), fill="#6A6A6A", width=2)
        card.text(time_text, (divider_x + 18, bottom - 31), 18, fill="#FFFFFF", anchor="ls")

    @staticmethod
    def _label(card: FlatCanvas, label: str, x: int, y: int, fill: str, ink: str, size: int) -> int:
        font = card.font(size)
        width = int(card.draw.textlength(label, font=font)) + 28
        card.draw.rounded_rectangle((x, y, x + width, y + size + 20), radius=3, fill=fill)
        card.text(label, (x + 14, y + 8), size, fill=ink)
        return width

    def _devblog_tags(self, card: FlatCanvas, tags: tuple[str, ...], x: int, y: int, available: int) -> None:
        cursor = x
        for value in tags[:3]:
            label = value.upper()
            font = card.font(18)
            width = int(card.draw.textlength(label, font=font)) + 24
            if cursor + width > x + available:
                break
            card.draw.rectangle((cursor, y, cursor + width, y + 42), fill="#17191B")
            card.text(label, (cursor + 12, y + 9), 18, fill="#FFFFFF")
            cursor += width + 8

    @staticmethod
    def _datetime(value: date | datetime | str) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return datetime(1970, 1, 1)

    def _official_date(self, value: date | datetime | str) -> str:
        parsed = self._datetime(value)
        return f"{parsed.year}年{parsed.month}月{parsed.day}日"

    def _devblog_date(self, value: date | datetime | str) -> tuple[str, str]:
        parsed = self._datetime(value)
        months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
        return f"{months[parsed.month - 1]} {parsed.day}, {parsed.year}", parsed.strftime("%H:%M")

    @staticmethod
    def _thumbnail(card: FlatCanvas, item: NewsItem, box: tuple[int, int, int, int], radius: int) -> None:
        x1, y1, x2, y2 = box
        if item.thumbnail:
            try:
                with Image.open(BytesIO(item.thumbnail)) as source:
                    fitted = ImageOps.fit(source.convert("RGB"), (x2 - x1, y2 - y1))
                    if radius:
                        mask = Image.new("L", fitted.size, 0)
                        ImageDraw.Draw(mask).rounded_rectangle((0, 0, fitted.width, fitted.height + radius), radius=radius, fill=255)
                        card.image.paste(fitted, (x1, y1), mask)
                    else:
                        card.image.paste(fitted, (x1, y1))
                return
            except (OSError, ValueError):
                pass
        card.draw.rectangle(box, fill="#304A5A")
        card.text((item.source.strip() or "讯")[0], ((x1 + x2) // 2, (y1 + y2) // 2), 64, fill="#A9EDF1", anchor="mm")

    def _empty(self, card: FlatCanvas) -> None:
        x, y = self.margin, self.top
        card.draw.rounded_rectangle((x, y, self.width - x, y + self.card_height), radius=8, fill="#202830")
        card.text("最近 7 日暂无新闻", (self.width // 2, y + 270), 38, fill=card.ink_muted, anchor="ma")


def render_information_report(items: list[NewsItem] | tuple[NewsItem, ...]) -> bytes:
    return InformationRenderer().render(items)
