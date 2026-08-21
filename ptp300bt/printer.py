from dataclasses import dataclass
import re
import sys
from types import SimpleNamespace

import serial
from serial.tools import list_ports

from labelmaker import do_print_job, reset_printer


@dataclass(frozen=True, slots=True)
class PrinterOptions:
    chain: bool = False
    auto_cut: bool = False
    end_margin: int = 0
    compression: bool = True


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


def print_raster(port: str, data: bytes, options: PrinterOptions) -> None:
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
            do_print_job(connection, args, data)
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
