from dataclasses import dataclass
from typing import TextIO
import re
import sys
from types import SimpleNamespace

import serial
from serial.tools import list_ports

from labelmaker import do_print_job, query_status as query_status_register, reset_printer
import ptstatus


@dataclass(frozen=True, slots=True)
class PrinterOptions:
    chain: bool = False
    auto_cut: bool = False
    end_margin: int = 0
    compression: bool = True


@dataclass(frozen=True, slots=True)
class TapeColors:
    """Display colours for the cassette reported by Brother's status protocol."""

    background_name: str = "White"
    background_hex: str = "#ffffff"
    foreground_name: str = "Black"
    foreground_hex: str = "#1a1a1a"


# Brother defines the protocol IDs and colour names, but does not publish an RGB
# palette. These screen colours are deliberately approximate representations.
TAPE_BACKGROUND_HEX = {
    0x01: "#ffffff", 0x02: "#808080", 0x03: "transparent", 0x04: "#d32f2f", 0x05: "#1565c0",
    0x06: "#ffc107", 0x07: "#2e7d32", 0x08: "#1f1f1f", 0x09: "transparent",
    0x20: "#fafafa", 0x21: "rgba(245,245,245,0.4)", 0x22: "#b0bec5", 0x23: "#d4af37",
    0x24: "#c0c0c0", 0x30: "#0d47a1", 0x31: "#b71c1c", 0x40: "#ff6e14",
    0x41: "#dfff00", 0x50: "#e0115f", 0x51: "#eceff1", 0x52: "#a2e8a2",
    0x60: "#ffe082", 0x61: "#f8bbd0", 0x62: "#b3e5fc", 0x70: "#f5f5f5",
    0x90: "#ffffff", 0x91: "#ffc107", 0xF0: "transparent",
    0xF1: "rgba(63,81,181,0.6)", 0xFF: "#ff00ff",
}
TAPE_FOREGROUND_HEX = {
    0x01: "#ffffff", 0x02: "#808080", 0x04: "#d32f2f", 0x05: "#1565c0",
    0x08: "#1a1a1a", 0x0A: "#d4af37", 0x62: "#0033a0", 0xF0: "transparent",
    0xF1: "#3f51b5", 0xFF: "#ff00ff",
}


def tape_colors_from_status(status: object) -> TapeColors:
    background_code = status.tape_bgcolor
    foreground_code = status.tape_fgcolor
    return TapeColors(
        background_name=ptstatus.TAPE_BGCOLORS.get(background_code, "Unknown"),
        background_hex=TAPE_BACKGROUND_HEX.get(background_code, "#ffffff"),
        foreground_name=ptstatus.TAPE_FGCOLORS.get(foreground_code, "Unknown"),
        foreground_hex=TAPE_FOREGROUND_HEX.get(foreground_code, "#1a1a1a"),
    )


@dataclass(frozen=True, slots=True)
class SerialPortInfo:
    device: str
    label: str
    description: str
    direction: str | None = None
    bluetooth_name: str | None = None


def bluetooth_address_from_hwid(hwid: str) -> str | None:
    """Extract the remote Bluetooth address from an outgoing SPP device ID."""
    if "BTHENUM" not in hwid.upper() or "LOCALMFG" in hwid.upper():
        return None
    match = re.search(r"[\\&]([0-9A-F]{12})_C[0-9A-F]+$", hwid, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _decode_bluetooth_name(value: object) -> str | None:
    if isinstance(value, str):
        return value.rstrip("\x00")
    if not isinstance(value, bytes):
        return None
    raw = value.rstrip(b"\x00")
    for encoding in ("utf-8", "utf-16-le"):
        try:
            name = raw.decode(encoding).rstrip("\x00")
            if name:
                return name
        except UnicodeDecodeError:
            continue
    return None


def _windows_bluetooth_names() -> dict[str, str]:
    if sys.platform != "win32":
        return {}
    try:
        import winreg

        path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
        names: dict[str, str] = {}
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as devices:
            index = 0
            while True:
                try:
                    address = winreg.EnumKey(devices, index).upper()
                    index += 1
                except OSError:
                    break
                try:
                    with winreg.OpenKey(devices, address) as device:
                        value, _ = winreg.QueryValueEx(device, "Name")
                    name = _decode_bluetooth_name(value)
                    if name:
                        names[address] = name
                except OSError:
                    continue
        return names
    except (ImportError, OSError):
        return {}


def _natural_port_key(device: str) -> tuple[str, int]:
    match = re.fullmatch(r"([^0-9]*)([0-9]+)", device)
    return (match.group(1), int(match.group(2))) if match else (device, 0)


def available_ports() -> list[SerialPortInfo]:
    paired_names = _windows_bluetooth_names()
    result: list[SerialPortInfo] = []
    for port in list_ports.comports():
        hwid = port.hwid or ""
        is_bluetooth = "BTHENUM" in hwid.upper()
        direction = None
        bluetooth_name = None
        description = port.description or port.device

        if is_bluetooth:
            direction = "Incoming" if "LOCALMFG" in hwid.upper() else "Outgoing"
            address = bluetooth_address_from_hwid(hwid)
            bluetooth_name = paired_names.get(address or "")
            if bluetooth_name:
                label = f"{port.device} — {bluetooth_name} ({direction})"
            else:
                label = f"{port.device} — {direction} Bluetooth port"
        else:
            label = f"{port.device} — {description}"

        result.append(
            SerialPortInfo(
                device=port.device,
                label=label,
                description=description,
                direction=direction,
                bluetooth_name=bluetooth_name,
            )
        )
    return sorted(result, key=lambda item: _natural_port_key(item.device))


def query_printer_status(port: str, output: TextIO | None = None) -> TapeColors:
    if not port:
        raise ValueError("Select a printer port.")
    try:
        connection = serial.Serial(port, timeout=10, write_timeout=10)
    except serial.SerialException as error:
        raise RuntimeError(f'Printer on serial port "{port}" is unavailable.') from error
    try:
        status = query_status_register(connection, output=output)
        return tape_colors_from_status(status)
    finally:
        try:
            reset_printer(connection)
        finally:
            connection.close()


def print_raster(port: str, data: bytes, options: PrinterOptions, output: TextIO | None = None) -> None:
    if not port:
        raise ValueError("Select a printer port.")
    args = SimpleNamespace(
        no_feed=options.chain,
        auto_cut=options.auto_cut,
        end_margin=options.end_margin,
        nocomp=not options.compression,
        no_print=False,
    )
    try:
        connection = serial.Serial(port, timeout=10, write_timeout=10)
    except serial.SerialException as error:
        raise RuntimeError(f'Printer on serial port "{port}" is unavailable.') from error
    try:
        try:
            do_print_job(connection, args, data, output=output)
        except SystemExit as error:
            # labelmaker is also a command-line program and reports printer
            # status failures with sys.exit().  Do not let that terminate the
            # Shiny worker/session when this module is used as a service.
            message = error.code if isinstance(error.code, str) else "Printer is not ready."
            raise RuntimeError(message) from error
    finally:
        try:
            reset_printer(connection)
        finally:
            connection.close()
