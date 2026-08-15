from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from ..core.config import config


ASSETS = Path(__file__).parent / "assets" / "kokomi"
FONT_REGULAR = ASSETS / "fonts" / "SHSCN.ttf"


class FlatCanvas:
    """Small shared drawing kit for Ursule's flat report cards."""

    background = "#F4F6F8"
    surface = "#FFFFFF"
    surface_muted = "#E9EDF2"
    ink = "#17212B"
    ink_muted = "#667584"
    accent = "#147D92"
    accent_soft = "#DDF2F5"
    warning = "#D96C39"
    success = "#2C8A66"
    divider = "#DDE3E9"

    def __init__(self, width: int, height: int) -> None:
        self.image = Image.new("RGB", (width, height), self.background)
        self.draw = ImageDraw.Draw(self.image)
        self.width = width
        self.height = height
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}

    def font(self, size: int, display: bool = False) -> ImageFont.FreeTypeFont:
        # Keep all report typography aligned with the Kokomi stats renderer.
        # ``display`` remains in the API so existing template calls stay simple.
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(FONT_REGULAR, size)
        return self._fonts[size]

    def text(
        self,
        value: object,
        xy: tuple[int, int],
        size: int,
        *,
        fill: str | tuple[int, int, int] | None = None,
        anchor: str = "la",
        display: bool = False,
    ) -> None:
        self.draw.text(xy, str(value), font=self.font(size, display), fill=fill or self.ink, anchor=anchor)

    def rounded(self, box: tuple[int, int, int, int], radius: int = 24, fill: str | None = None) -> None:
        self.draw.rounded_rectangle(box, radius=radius, fill=fill or self.surface)

    def pill(self, label: str, xy: tuple[int, int], *, fill: str, ink: str, size: int = 26) -> int:
        font = self.font(size)
        width = int(self.draw.textlength(label, font=font)) + 34
        x, y = xy
        self.draw.rounded_rectangle((x, y, x + width, y + size + 22), radius=22, fill=fill)
        self.draw.text((x + 17, y + 8), label, font=font, fill=ink)
        return width

    def progress(
        self,
        box: tuple[int, int, int, int],
        value: float,
        *,
        fill: str | None = None,
        track: str | None = None,
        radius: int | None = None,
    ) -> None:
        x1, y1, x2, y2 = box
        corner_radius = max(1, (y2 - y1) // 2) if radius is None else max(0, radius)
        self.draw.rounded_rectangle(box, radius=corner_radius, fill=track or self.surface_muted)
        ratio = min(1.0, max(0.0, value))
        if ratio:
            right = max(x1 + (y2 - y1), int(x1 + (x2 - x1) * ratio))
            if fill:
                self.draw.rounded_rectangle((x1, y1, right, y2), radius=corner_radius, fill=fill)
            else:
                self._rating_gradient((x1, y1, right, y2), corner_radius)

    def _rating_gradient(self, box: tuple[int, int, int, int], radius: int) -> None:
        """Draw the Kokomi '战舰仙人' lavender-aqua-green gradient."""
        x1, y1, x2, y2 = box
        width, height = max(1, x2 - x1), max(1, y2 - y1)
        stops = ((199, 150, 190), (105, 221, 216), (174, 221, 139))
        gradient = Image.new("RGB", (width, height))
        pixels = gradient.load()
        for x in range(width):
            position = x / max(1, width - 1)
            segment = min(1, int(position * 2))
            amount = position * 2 - segment
            start, end = stops[segment], stops[segment + 1]
            color = tuple(round(start[channel] + (end[channel] - start[channel]) * amount) for channel in range(3))
            for y in range(height):
                pixels[x, y] = color
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
        self.image.paste(gradient, (x1, y1), mask)

    def wrapped_lines(self, value: str, width: int, size: int, max_lines: int) -> list[str]:
        """Wrap CJK and latin text by measured width, adding an ellipsis if clipped."""
        font = self.font(size)
        lines: list[str] = []
        current = ""
        remaining = ""
        for index, char in enumerate(str(value).strip()):
            candidate = current + char
            if current and self.draw.textlength(candidate, font=font) > width:
                lines.append(current.rstrip())
                current = char.lstrip()
                if len(lines) == max_lines:
                    remaining = str(value).strip()[index:]
                    break
            else:
                current = candidate
        if current and len(lines) < max_lines:
            lines.append(current.rstrip())
        if remaining and lines:
            while lines[-1] and self.draw.textlength(lines[-1] + "…", font=font) > width:
                lines[-1] = lines[-1][:-1]
            lines[-1] += "…"
        return lines

    def footer(self, label: str = "URSULE BOT") -> None:
        y = self.height - 66
        self.draw.line((70, y - 22, self.width - 70, y - 22), fill=self.divider, width=2)
        self.text(label, (70, y), 22, fill=self.ink_muted, anchor="ls")
        stamp = datetime.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d %H:%M")
        self.text(stamp, (self.width - 70, y), 22, fill=self.ink_muted, anchor="rs")

    def png(self) -> bytes:
        output = BytesIO()
        self.image.save(output, format="PNG", optimize=True)
        self.image.close()
        return output.getvalue()
