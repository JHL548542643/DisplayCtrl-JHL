"""EDID identity, capability parsing, and handle matching.

Display index is not an identity. Matching prefers a parsed EDID block and
otherwise requires the same geometry the probe just saw.
"""

from __future__ import annotations

import re

from displayctl.models import RawMonitor

_EDID_HEADER = bytes((0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00))
_ID_RE = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")


def slug(text: str) -> str:
    chars: list[str] = []
    for ch in text.strip():
        chars.append(ch if ch.isalnum() or ch in "._-" else "_")
    value = "".join(chars).strip("._-")
    return (value[:64] or "x")


def encode_edid(
    manufacturer: str,
    product: int,
    serial: int = 0,
    *,
    serial_text: str | None = None,
    name: str | None = None,
) -> bytes:
    """Build a 128-byte EDID block for the demo backend and tests.

    This does not program a display. It only makes recognizable identity bytes.
    """
    if len(manufacturer) != 3 or not manufacturer.isalpha() or not manufacturer.isupper():
        raise ValueError("manufacturer must be three uppercase letters")
    block = bytearray(128)
    block[:8] = _EDID_HEADER
    packed = 0
    for ch in manufacturer:
        packed = (packed << 5) | (ord(ch) - 64)
    block[8:10] = packed.to_bytes(2, "big")
    block[10:12] = int(product).to_bytes(2, "little")
    block[12:16] = int(serial).to_bytes(4, "little")
    if name:
        block[54:72] = _text_descriptor(0xFC, name)
    if serial_text:
        block[72:90] = _text_descriptor(0xFF, serial_text)
    block[127] = (-sum(block[:127])) & 0xFF
    return bytes(block)


def _text_descriptor(tag: int, text: str) -> bytes:
    body = bytearray(18)
    body[3] = tag
    raw = text.encode("ascii", "replace")[:13]
    body[5 : 5 + len(raw)] = raw
    if 5 + len(raw) < 18:
        body[5 + len(raw)] = 0x0A
    return bytes(body)


class EdidInfo:
    def __init__(
        self,
        manufacturer: str,
        product_code: str,
        serial: str | None,
        name: str | None,
    ) -> None:
        self.manufacturer = manufacturer
        self.product_code = product_code
        self.serial = serial
        self.name = name


def parse_edid(edid: bytes | None) -> EdidInfo | None:
    if not edid or len(edid) < 128:
        return None
    block = bytes(edid[:128])
    if block[:8] != _EDID_HEADER or sum(block) % 256 != 0:
        return None
    manufacturer = _manufacturer(block)
    if manufacturer is None:
        return None
    product = int.from_bytes(block[10:12], "little")
    serial_num = int.from_bytes(block[12:16], "little")
    name = _descriptor_text(block, 0xFC)
    serial_text = _descriptor_text(block, 0xFF)
    serial = serial_text or (str(serial_num) if serial_num else None)
    return EdidInfo(manufacturer, f"{product:04X}", serial, name)


def _manufacturer(block: bytes) -> str | None:
    raw = int.from_bytes(block[8:10], "big")
    chars: list[str] = []
    for shift in (10, 5, 0):
        value = (raw >> shift) & 0x1F
        if value < 1 or value > 26:
            return None
        chars.append(chr(value + 64))
    return "".join(chars)


def _descriptor_text(block: bytes, tag: int) -> str | None:
    for offset in (54, 72, 90, 108):
        desc = block[offset : offset + 18]
        if desc[0:3] != b"\x00\x00\x00" or desc[3] != tag:
            continue
        text = desc[5:18].split(b"\n", 1)[0].split(b"\x00", 1)[0]
        cleaned = text.decode("ascii", "replace").strip()
        if cleaned:
            return cleaned
    return None


def parse_caps_model(caps: str | None) -> str | None:
    """Pull ``model(...)`` out of a capabilities string. Same rule as the first CLI."""
    if not caps:
        return None
    key = "model("
    start = caps.find(key)
    if start < 0:
        return None
    start += len(key)
    end = caps.find(")", start)
    if end < 0:
        return None
    model = caps[start:end].strip()
    return model or None


def declared_vcp_codes(caps: str | None) -> frozenset[int] | None:
    """Top-level codes inside ``vcp(...)``, or None when that section is missing.

    Values nested under a code, such as ``14(05 08)``, are not codes. The set
    stays inside the library: the API exposes only the features it knows how
    to describe, not this list.
    """
    body = _vcp_section(caps)
    if body is None:
        return None
    tokens = re.findall(r"\b[0-9a-fA-F]{2}\b", _strip_parentheticals(body))
    return frozenset(int(token, 16) for token in tokens)


def caps_declares_luminance(caps: str | None) -> bool | None:
    """True/False when a vcp() section exists, else None."""
    codes = declared_vcp_codes(caps)
    if codes is None:
        return None
    return 0x10 in codes


def caps_declares_code(caps: str | None, code: int) -> bool | None:
    """True/False when a vcp() section exists, else None. Presence only, not a reading."""
    codes = declared_vcp_codes(caps)
    if codes is None:
        return None
    return code in codes


def caps_declares_contrast(caps: str | None) -> bool | None:
    """True/False when a vcp() section exists, else None. Presence only, not a reading."""
    return caps_declares_code(caps, 0x12)


def caps_declares_volume(caps: str | None) -> bool | None:
    """True/False when a vcp() section exists, else None. Presence only, not a reading."""
    return caps_declares_code(caps, 0x62)


def caps_declares_input_source(caps: str | None) -> bool | None:
    """True/False when a vcp() section exists, else None. Presence only, not a reading."""
    return caps_declares_code(caps, 0x60)


def caps_declares_power_mode(caps: str | None) -> bool | None:
    """True/False when a vcp() section exists, else None. Presence only, not a reading."""
    return caps_declares_code(caps, 0xD6)


def caps_declares_rgb_gains(caps: str | None) -> bool | None:
    """True when any RGB gain code is declared; False when vcp() omits all three; else None."""
    codes = declared_vcp_codes(caps)
    if codes is None:
        return None
    return bool(codes & {0x16, 0x18, 0x1A})


def _vcp_section(caps: str | None) -> str | None:
    if not caps:
        return None
    marker = "vcp("
    start = caps.lower().find(marker)
    if start < 0:
        return None
    index = start + len(marker)
    depth = 1
    chars: list[str] = []
    while index < len(caps) and depth:
        char = caps[index]
        if char == "(":
            depth += 1
            chars.append(char)
        elif char == ")":
            depth -= 1
            if depth:
                chars.append(char)
        else:
            chars.append(char)
        index += 1
    if depth != 0:
        return None
    return "".join(chars)


def _strip_parentheticals(body: str) -> str:
    """Blank out nested value lists so their bytes are not read as VCP codes."""
    out: list[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
            out.append(" ")
        elif char == ")":
            depth = max(0, depth - 1)
            out.append(" ")
        elif depth == 0:
            out.append(char)
        else:
            out.append(" ")
    return "".join(out)


class Identity:
    def __init__(
        self,
        id: str,
        quality: str,
        stable: bool,
        model: str | None,
        manufacturer: str | None,
        product_code: str | None,
        serial: str | None,
    ) -> None:
        if not _ID_RE.fullmatch(id):
            raise ValueError(f"monitor id is not safe to put in a URL: {id!r}")
        self.id = id
        self.quality = quality
        self.stable = stable
        self.model = model
        self.manufacturer = manufacturer
        self.product_code = product_code
        self.serial = serial


def identify(raw: RawMonitor) -> Identity:
    parsed = parse_edid(raw.edid)
    caps_model = parse_caps_model(raw.caps)
    model = caps_model or (parsed.name if parsed else None)
    if parsed and parsed.serial:
        return Identity(
            f"edid:{parsed.manufacturer}:{parsed.product_code}:{slug(parsed.serial)}",
            "strong",
            True,
            model,
            parsed.manufacturer,
            parsed.product_code,
            parsed.serial,
        )
    if parsed:
        return Identity(
            f"edid:{parsed.manufacturer}:{parsed.product_code}:noserial",
            "model",
            False,
            model,
            parsed.manufacturer,
            parsed.product_code,
            None,
        )
    if caps_model:
        return Identity(
            f"model:{slug(caps_model)}",
            "model",
            False,
            caps_model,
            None,
            None,
            None,
        )
    fallback = slug(raw.description or raw.device or "monitor")
    return Identity(f"unstable:{fallback}", "unstable", False, None, None, None, None)


def same_raw(left: RawMonitor, right: RawMonitor) -> bool:
    """True when a newly opened handle is the same panel the probe selected.

    EDID wins over the ``\\\\.\\DISPLAYn`` name, which Windows reuses.
    Without EDID, a geometry change is a refuse, not a guess.
    """
    if left.edid and right.edid:
        return left.edid == right.edid
    if left.edid or right.edid:
        return False
    return (
        left.device == right.device
        and left.description == right.description
        and left.rect == right.rect
        and left.primary == right.primary
    )
