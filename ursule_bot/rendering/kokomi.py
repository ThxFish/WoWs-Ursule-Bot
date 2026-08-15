from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from ..centers.stats.service import Metric, PeriodMetric, PersonalStats
from ..core.config import config


ASSETS = Path(__file__).parent / "assets" / "kokomi"
INSERT_Y = 2325
INSERT_HEIGHT = 600
FOOTER_Y = 3860
CANVAS_SIZE = (2428, 4050)
TEXT_COLORS = {
    "light": ((0, 0, 0), (20, 20, 20), (75, 75, 75), (125, 125, 125)),
    "dark": ((255, 255, 255), (225, 225, 225), (180, 180, 180), (130, 130, 130)),
}
RATING_COLORS = {
    "light": ((127, 127, 127), (205, 51, 51), (254, 121, 3), (255, 193, 7), (68, 179, 0), (49, 128, 0), (52, 186, 211), (211, 33, 213), (115, 13, 189)),
    "dark": ((105, 105, 105), (125, 0, 0), (168, 66, 0), (183, 170, 0), (99, 140, 11), (0, 113, 48), (0, 117, 169), (234, 63, 224), (151, 38, 176)),
}
RATING_TEXT = ("水平未知", "还需努力", "低于平均", "平均水平", "好", "很好", "非常好", "大佬平均", "神佬平均")
RATING_LABEL_WIDTH = (430, 430, 430, 430, 210, 280, 355, 430, 430)
CLAN_COLORS = ((121, 61, 182), (144, 223, 143), (234, 197, 0), (147, 147, 147), (184, 115, 51), (147, 147, 147))


class KokomiRenderer:
    """Pixel-compatible renderer for Kokomi Bot's classic basic stats card."""

    def __init__(self, theme: str = "light") -> None:
        self.theme = theme if theme in {"light", "dark"} else "light"
        self.text = TEXT_COLORS[self.theme]
        self.rating = RATING_COLORS[self.theme]
        self.section_title = (27, 27, 27) if self.theme == "light" else (225, 225, 225)
        self.fonts: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}

    def _font(self, size: int, index: int = 1) -> ImageFont.FreeTypeFont:
        pixel_size = round(300 / 72 * size)
        key = (index, pixel_size)
        if key not in self.fonts:
            name = "SHSCN.ttf" if index == 1 else "NZBZ.ttf"
            self.fonts[key] = ImageFont.truetype(ASSETS / "fonts" / name, pixel_size)
        return self.fonts[key]

    def _text(self, draw: ImageDraw.ImageDraw, value: object, xy: tuple[int, int], size: int, color: tuple[int, int, int], align: str = "left", font_index: int = 1) -> None:
        value = str(value)
        font = self._font(size, font_index)
        x, y = xy
        width = draw.textlength(value, font=font)
        if align == "center":
            x -= width / 2
        elif align == "right":
            x -= width
        draw.text((x, y), value, fill=color, font=font)

    @staticmethod
    def _paste(canvas: Image.Image, path: Path, xy: tuple[int, int]) -> None:
        with Image.open(path) as source:
            layer = source.convert("RGBA")
            canvas.alpha_composite(layer, xy)

    def _paste_expanded_background(self, canvas: Image.Image) -> None:
        with Image.open(ASSETS / "content" / self.theme / "cn" / "basic.png") as source:
            layer = source.convert("RGBA")
            canvas.alpha_composite(layer.crop((0, 0, CANVAS_SIZE[0], INSERT_Y)), (0, 0))
            # Duplicate the first four rows of the original "ship" section so its header
            # icons, spacing, dividers and typography remain pixel-compatible.
            canvas.alpha_composite(layer.crop((0, 1637, CANVAS_SIZE[0], 2237)), (0, INSERT_Y))
            canvas.alpha_composite(layer.crop((0, INSERT_Y, CANVAS_SIZE[0], 3260)), (0, INSERT_Y + INSERT_HEIGHT))

    def _metric_row(self, draw: ImageDraw.ImageDraw, metric: Metric, y: int) -> None:
        values = (
            (metric.battles_count, 588, self.text[2]),
            (self._rating_label(metric), 955, self.rating[metric.rating_class]),
            (metric.win_rate, 1307, self.rating[metric.win_rate_class]),
            (metric.avg_damage, 1613, self.rating[metric.avg_damage_class]),
            (metric.avg_frags, 1909, self.rating[metric.avg_frags_class]),
            (metric.avg_exp, 2177, self.text[2]),
        )
        for value, x, color in values:
            self._text(draw, value, (x, y), 14, color, "center")

    def _change_color(self, delta: float) -> tuple[int, int, int]:
        if delta > 0:
            return self.rating[5]
        if delta < 0:
            return self.rating[1]
        return self.text[2]

    @staticmethod
    def _delta_text(delta: float, decimals: int = 0, percent: bool = False) -> str:
        if abs(delta) < (0.005 if decimals else 0.5):
            return "±0.00%" if percent else ("±0.00" if decimals else "±0")
        sign = "+" if delta > 0 else "-"
        magnitude = f"{abs(delta):.{decimals}f}" if decimals else f"{abs(round(delta)):,}".replace(",", " ")
        return f"{sign}{magnitude}{'%' if percent else ''}"

    def _section_labels(
        self,
        canvas: Image.Image,
        section_y: int,
        title: str,
        first_header: str,
        rows: tuple[str, ...],
        *,
        row_x: int,
        row_align: str = "left",
        clear_to_x: int = 445,
    ) -> None:
        draw = ImageDraw.Draw(canvas)

        self._section_title(canvas, section_y, title)

        header_fill = canvas.getpixel((440, section_y + 145))
        draw.rectangle((165, section_y + 118, 445, section_y + 180), fill=header_fill)
        self._text(draw, first_header, (285, section_y + 131), 11, self.text[2], "center")

        for index, label in enumerate(rows):
            y = section_y + 218 + index * 90
            row_fill = canvas.getpixel((450, y + 20))
            draw.rectangle((160, y - 4, clear_to_x, y + 60), fill=row_fill)
            self._text(draw, label, (row_x, y + 4), 11, self.text[2], row_align)

    def _section_title(self, canvas: Image.Image, section_y: int, title: str) -> None:
        draw = ImageDraw.Draw(canvas)
        panel_fill = canvas.getpixel((2200, section_y + 35))
        # Static titles in basic.png include pale vertical and underline strips.
        # Clear the complete decoration area so no remnants show around titles.
        draw.rectangle((97, section_y, 2331, section_y + 116), fill=panel_fill)
        self._text(draw, title, (150, section_y + 18), 16, self.section_title)

    def _dog_tag(self, canvas: Image.Image, stats: PersonalStats) -> None:
        """Composite the player's WoWS dog tag at Kokomi V4's original bounds."""
        from ..centers.stats.service import dog_tag_path

        path = dog_tag_path(stats.account_id)
        if not stats.dog_tag_url or not path.exists():
            return
        try:
            with Image.open(path) as source:
                badge = source.convert("RGBA").resize((419, 419), Image.Resampling.LANCZOS)
                canvas.alpha_composite(badge, (1912, 129))
                badge.close()
        except (OSError, ValueError):
            return

    def _comparison_section(self, canvas: Image.Image, stats: PersonalStats) -> None:
        defaults = {
            "previous": PeriodMetric("上次查询"),
            "week": PeriodMetric("最近一周"),
            "month": PeriodMetric("最近一月"),
            "half_year": PeriodMetric("最近半年"),
        }
        trends = tuple(stats.periods.get(key, defaults[key]) for key in defaults)
        self._section_labels(
            canvas,
            INSERT_Y,
            "战绩变化",
            "查询周期",
            tuple(trend.label for trend in trends),
            row_x=285,
            row_align="center",
        )
        draw = ImageDraw.Draw(canvas)

        gap_fill = canvas.getpixel((50, INSERT_Y + 580))
        draw.rectangle((97, INSERT_Y + 558, 2331, INSERT_Y + 599), fill=gap_fill)
        for index, trend in enumerate(trends):
            y = INSERT_Y + 218 + index * 90
            if not trend.available:
                self._text(draw, "历史数据积累中", (1380, y), 14, self.text[3], "center")
                continue
            metrics = (
                (trend.battles_delta, self._delta_text(trend.battles_delta), 588),
                (trend.rating_delta, self._delta_text(trend.rating_delta), 955),
                (trend.win_rate_delta, self._delta_text(trend.win_rate_delta, 2, True), 1307),
                (trend.avg_damage_delta, self._delta_text(trend.avg_damage_delta), 1613),
                (trend.avg_frags_delta, self._delta_text(trend.avg_frags_delta, 2), 1909),
                (trend.avg_exp_delta, self._delta_text(trend.avg_exp_delta), 2177),
            )
            for delta, value, x in metrics:
                self._text(draw, value, (x, y), 14, self._change_color(delta), "center")

    @staticmethod
    def _rating_label(metric: Metric) -> str:
        if metric.rating == "-":
            return "-"
        return f"{RATING_TEXT[metric.rating_class]}(+{metric.rating_next})"

    def render(self, stats: PersonalStats) -> bytes:
        background = (248, 249, 251, 255) if self.theme == "light" else (49, 49, 49, 255)
        canvas = Image.new("RGBA", CANVAS_SIZE, background)
        self._paste_expanded_background(canvas)
        self._paste(canvas, ASSETS / "components" / "header" / f"{self.theme}.png", (97, 130))
        self._dog_tag(canvas, stats)
        draw = ImageDraw.Draw(canvas)

        self._text(draw, stats.nickname, (171, 155), 22, self.text[1])
        self._text(draw, stats.region, (348, 272), 10, self.text[3], "center")
        self._text(draw, stats.account_id, (586, 272), 10, self.text[3], "center")
        self._text(draw, "所属工会:", (169, 358), 14, self.text[2])
        self._text(draw, f"[{stats.clan_tag}]" if stats.clan_tag else "None", (530, 358), 14, CLAN_COLORS[min(max(stats.clan_league, 0), 5)])
        self._text(draw, "注册时间:", (169, 448), 14, self.text[2])
        created = datetime.fromtimestamp(stats.created_at, ZoneInfo(config.timezone)).strftime("%Y-%m-%d") if stats.created_at else "-"
        self._text(draw, created, (530, 448), 14, self.text[1])

        overall = stats.overall
        rating_asset = ASSETS / "content" / "rating" / "pr" / "cn" / self.theme / f"{overall.rating_class}.png"
        with Image.open(rating_asset) as bar:
            canvas.paste(bar.convert("RGBA"), (132, 627))
        rating_value = int(overall.rating.replace(" ", "")) if overall.rating != "-" else 0
        next_title = "超出最高评级" if rating_value >= 3000 else "距离下一评级"
        self._text(draw, f"{next_title}:    +{overall.rating_next}", (132 + RATING_LABEL_WIDTH[overall.rating_class] + 10, 690), 8, (255, 255, 255))
        self._text(draw, overall.rating, (2284, 642), 20, (255, 255, 255), "right")

        summary = (
            (overall.battles_count, 324, self.text[2]),
            (overall.win_rate, 770, self.rating[overall.win_rate_class]),
            (overall.avg_damage, 1216, self.rating[overall.avg_damage_class]),
            (overall.avg_frags, 1662, self.rating[overall.avg_frags_class]),
            (overall.avg_exp, 2108, self.text[2]),
        )
        for value, x, color in summary:
            self._text(draw, value, (x, 860), 20, color, "center")

        for index, name in enumerate(("pvp_solo", "pvp_div2", "pvp_div3", "rank_solo")):
            self._metric_row(draw, stats.battle_type.get(name, Metric()), 1258 + 90 * index)
        for index, name in enumerate(("AirCarrier", "Battleship", "Cruiser", "Destroyer", "Submarine")):
            self._metric_row(draw, stats.ship_type.get(name, Metric()), 1855 + 90 * index)

        # The source PNG contains fixed Chinese labels. Redraw every statistics
        # section through one code path so their typography is genuinely shared.
        self._section_labels(
            canvas,
            1040,
            "总体数据",
            "类型数据",
            ("单野 SOLO", "双排 DIV 2", "三排 DIV 3", "排位 RANK"),
            row_x=168,
        )
        self._section_labels(
            canvas,
            1637,
            "船只数据",
            "船只数据",
            ("空母", "战列", "巡洋", "驱逐", "潜艇"),
            row_x=192,
            clear_to_x=300,
        )
        self._section_title(canvas, INSERT_Y + INSERT_HEIGHT, "数据图表")

        values = [int(stats.chart_data.get(str(tier), 0)) for tier in range(1, 12)]
        maximum = max(100, (max(values, default=0) // 100 + 1) * 100)
        chart_color = (0, 117, 169) if self.theme == "dark" else (52, 186, 211)
        for index, value in enumerate(values):
            top = 2542 + INSERT_HEIGHT + int(500 - value / maximum * 500)
            x1 = 272 + 129 * index
            draw.rectangle((x1, top, 350 + 129 * index, 3045 + INSERT_HEIGHT), fill=chart_color)
            self._text(draw, value, (311 + 129 * index, top - 40), 8, self.text[1], "center")

        self._comparison_section(canvas, stats)
        self._paste(canvas, ASSETS / "components" / "footer" / f"{self.theme}.png", (97, FOOTER_Y))
        draw = ImageDraw.Draw(canvas)
        self._text(draw, "Ursule Bot  |  Kokomi Stats", (145, FOOTER_Y + 23), 12, self.text[3])
        self._text(draw, datetime.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d %H:%M:%S"), (1212, FOOTER_Y + 23), 12, self.text[3])
        self._text(draw, "Kokomi V4 Style", (2283, FOOTER_Y + 32), 8, self.text[3], "right")
        output = BytesIO()
        canvas.convert("RGB").save(output, format="PNG", optimize=True)
        canvas.close()
        return output.getvalue()


def render_personal_stats(stats: PersonalStats, theme: str = "light") -> bytes:
    return KokomiRenderer(theme).render(stats)
