from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LabelSpec:
    """User-editable properties of a text label."""

    text: str
    font_path: str
    alignment: str = "center"
    horizontal_padding: int = 5
    end_margin: int = 0
    line_spacing: float = 1.2
    vertical_shift: int = 0
    threshold: int = 75
    fixed_width_mm: float | None = None

    def validate(self) -> None:
        if not self.text.strip():
            raise ValueError("Enter some label text.")
        if self.alignment not in {"left", "center", "right"}:
            raise ValueError("Alignment must be left, center, or right.")
        if not 0 <= self.horizontal_padding <= 200:
            raise ValueError("Horizontal padding must be between 0 and 200 dots.")
        if not 0 <= self.end_margin <= 1000:
            raise ValueError("End margin must be between 0 and 1000 dots.")
        if not 0.8 <= self.line_spacing <= 3:
            raise ValueError("Line spacing must be between 0.8 and 3.0.")
        if not 0 <= self.threshold <= 255:
            raise ValueError("Threshold must be between 0 and 255.")
        if self.fixed_width_mm is not None and not 5 <= self.fixed_width_mm <= 473:
            raise ValueError("Fixed label width must be between 5 and 473 mm.")
