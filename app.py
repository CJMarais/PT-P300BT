import asyncio
import base64
import io
from pathlib import Path

from shiny import App, reactive, render, ui

from ptp300bt.models import LabelSpec
from ptp300bt.printer import PrinterOptions, available_ports, print_raster
from ptp300bt.rendering import add_preview_guides, render_label, valid_font_sizes


def system_fonts() -> dict[str, str]:
    font_dir = Path("C:/Windows/Fonts")
    preferred = ["arial.ttf", "calibri.ttf", "segoeui.ttf", "consola.ttf"]
    found = {name: font_dir / name for name in preferred if (font_dir / name).is_file()}
    if not found and font_dir.is_dir():
        found = {path.name: path for path in sorted(font_dir.glob("*.ttf"))[:50]}
    return {str(path): name.rsplit(".", 1)[0].replace("_", " ").title() for name, path in found.items()}


FONTS = system_fonts()
CABLE_DIAMETERS = {
    str(value / 2): f"{value / 2:g} mm" for value in range(4, 41)
}

app_ui = ui.page_navbar(
    ui.nav_panel(
        "Create label",
        ui.div(
            ui.layout_columns(
                ui.card(
                    ui.card_header("Label editor"),
                    ui.input_text_area("text", "Label text", "SERVER RACK 3", rows=4),
                    ui.input_select("font", "Font", choices=FONTS),
                    ui.input_select(
                        "font_size",
                        "Font size",
                        choices={"auto": "Auto — largest fit"},
                    ),
                    ui.input_radio_buttons(
                        "alignment", "Alignment", {"left": "Left", "center": "Center", "right": "Right"},
                        selected="center", inline=True,
                    ),
                    ui.layout_columns(
                        ui.input_numeric("padding", "Side padding (dots)", 5, min=0, max=200),
                        ui.input_numeric("margin", "End margin (dots)", 0, min=0, max=1000),
                    ),
                    ui.input_checkbox("fixed_width", "Use fixed label width", False),
                    ui.panel_conditional(
                        "input.fixed_width === true",
                        ui.input_numeric("width_mm", "Minimum width (mm)", 50, min=5, max=473),
                    ),
                    ui.input_checkbox("cable_mode", "Cable label — print text twice", False),
                    ui.panel_conditional(
                        "input.cable_mode === true",
                        ui.layout_columns(
                            ui.input_select(
                                "cable_diameter",
                                "Cable diameter",
                                choices=CABLE_DIAMETERS,
                                selected="6.0",
                            ),
                            ui.input_numeric(
                                "cable_buffer",
                                "Buffer each side (mm)",
                                2.0,
                                min=0,
                                max=20,
                                step=0.5,
                            ),
                        ),
                    ),
                    ui.input_slider("line_spacing", "Line spacing", 0.8, 2.0, 1.2, step=0.05),
                    ui.input_checkbox("show_guides", "Show rulers and print boundaries", False),
                    full_screen=True,
                ),
                ui.card(
                    ui.card_header("Print preview"),
                    ui.output_ui("preview"),
                    ui.output_ui("metrics"),
                    ui.hr(),
                    ui.layout_columns(
                        ui.input_select("port", "Printer port", choices={}),
                        ui.input_action_button("refresh_ports", "Refresh ports", class_="btn-outline-secondary mt-4"),
                    ),
                    ui.layout_columns(
                        ui.input_checkbox("chain", "Chain printing (no feed)", False),
                        ui.input_checkbox("auto_cut", "Cut/boundary mark", False),
                    ),
                    ui.input_task_button("print", "Print label", class_="btn-primary w-100"),
                    ui.div(ui.output_text_verbatim("print_log"), class_="print-console mt-3"),
                    ui.div(ui.output_ui("print_status"), class_="status-panel mt-3"),
                    full_screen=True,
                ),
                col_widths=(5, 7),
            ),
            class_="app-shell py-4",
        ),
    ),
    title="P-touch Studio",
    window_title="P-touch Studio",
    header=ui.tags.link(rel="stylesheet", href="styles.css"),
)


def server(input, output, session):
    def refresh_ports() -> None:
        ports = available_ports()
        choices = {port.device: port.label for port in ports}
        preferred = next(
            (port.device for port in ports if port.direction == "Outgoing" and "P300" in (port.bluetooth_name or "").upper()),
            ports[0].device if ports else None,
        )
        ui.update_select("port", choices=choices, selected=preferred)

    @reactive.effect
    def _initial_ports():
        refresh_ports()

    @reactive.effect
    @reactive.event(input.refresh_ports)
    def _refresh_ports():
        refresh_ports()

    @reactive.calc
    def rendered_label():
        if not FONTS:
            raise ValueError("No TrueType fonts were found in C:/Windows/Fonts.")
        spec = LabelSpec(
            text=input.text(),
            font_path=input.font(),
            alignment=input.alignment(),
            horizontal_padding=int(input.padding()),
            end_margin=int(input.margin()),
            line_spacing=float(input.line_spacing()),
            fixed_width_mm=float(input.width_mm()) if input.fixed_width() else None,
            font_size=None if input.font_size() == "auto" else int(input.font_size()),
            cable_diameter_mm=float(input.cable_diameter()) if input.cable_mode() else None,
            cable_buffer_mm=float(input.cable_buffer()),
        )
        return render_label(spec)

    @reactive.effect
    def _update_font_sizes():
        sizes = valid_font_sizes(input.text(), input.font(), float(input.line_spacing()))
        choices = {"auto": f"Auto — largest fit ({sizes[-1]} pt)" if sizes else "Auto — largest fit"}
        choices.update({str(size): f"{size} pt" for size in reversed(sizes)})
        current = input.font_size()
        ui.update_select(
            "font_size",
            choices=choices,
            selected=current if current in choices else "auto",
        )

    @render.ui
    def preview():
        try:
            result = rendered_label()
        except ValueError as error:
            return ui.div(str(error), class_="preview-stage preview-error")
        buffer = io.BytesIO()
        preview_image = add_preview_guides(result.preview) if input.show_guides() else result.preview
        preview_image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return ui.div(
            ui.tags.img(src=f"data:image/png;base64,{encoded}", class_="tape-preview", alt="Label preview"),
            class_="preview-stage",
        )

    @render.ui
    def metrics():
        try:
            result = rendered_label()
        except ValueError:
            return None
        cable_detail = (
            f" · {result.cable_gap_mm:.1f} mm cable gap" if result.cable_gap_mm is not None else ""
        )
        return ui.p(
            f"{result.printed_length_mm:.1f} mm label · {result.used_length_mm:.1f} mm tape used · "
            f"font size {result.font_size}{cable_detail}",
            class_="label-metrics mt-3",
        )

    @ui.bind_task_button(button_id="print")
    @reactive.extended_task
    async def run_print(port: str, data: bytes, chain: bool, auto_cut: bool, end_margin: int):
        print_output = io.StringIO()
        try:
            await asyncio.to_thread(
                print_raster,
                port,
                data,
                PrinterOptions(chain=chain, auto_cut=auto_cut, end_margin=end_margin),
                print_output,
            )
        except Exception as error:
            return False, str(error), print_output.getvalue()
        return True, f"Printed successfully on {port}.", print_output.getvalue()

    @reactive.effect
    @reactive.event(input.print)
    def _print():
        try:
            result = rendered_label()
            port = input.port()
            if not port:
                ui.notification_show("No printer port is available.", type="error")
                return
            run_print(port, result.raster_data, input.chain(), input.auto_cut(), int(input.margin()))
        except ValueError as error:
            ui.notification_show(str(error), type="error")

    @render.ui
    def print_status():
        try:
            success, message, _log = run_print.result()
        except Exception:
            return None
        return ui.div(message, class_="text-success" if success else "text-danger")

    @render.text
    def print_log():
        try:
            _success, _message, log = run_print.result()
        except Exception:
            return "Printer output will appear here."
        return log or "No printer output was produced."


app = App(app_ui, server, static_assets=Path(__file__).parent / "www")
