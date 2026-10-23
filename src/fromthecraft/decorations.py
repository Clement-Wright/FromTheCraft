"""Read the verified 4.3.x decoration packet in local FtD VehicleData.

Numeric schema checked against SuperLoader, Decoration and DecorationManager in
the installed game. No game code or assets are redistributed here.
"""

import base64
import struct
import uuid

import numpy as np


def unity_euler(angles):
    x, y, z = np.deg2rad(angles)
    cx, cy, cz = np.cos((x, y, z))
    sx, sy, sz = np.sin((x, y, z))
    rx = np.array(((1, 0, 0), (0, cx, -sx), (0, sx, cx)))
    ry = np.array(((cy, 0, sy), (0, 1, 0), (-sy, 0, cy)))
    rz = np.array(((cz, -sz, 0), (sz, cz, 0), (0, 0, 1)))
    return ry @ rx @ rz


def packet_headers(encoded, id_bytes=8):
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid FtD binary payload encoding") from exc
    if len(data) > 24 * 1024**2:
        raise ValueError("FtD binary payload exceeds 24 MiB")
    cursor, packets = 0, 0
    while cursor < len(data):
        packets += 1
        if packets > 500_000 or cursor + id_bytes + 6 > len(data):
            raise ValueError("Truncated or excessive FtD binary packets")
        identifier = int.from_bytes(data[cursor : cursor + id_bytes], "little")
        cursor += id_bytes
        header_length, unsorted = struct.unpack_from("<HH", data, cursor)
        cursor += 4
        length = 0
        for _ in range(100):
            if cursor + 2 > len(data):
                raise ValueError("Truncated FtD packet length")
            piece = struct.unpack_from("<H", data, cursor)[0]
            cursor += 2
            length += piece
            if piece < 65535:
                break
        else:
            raise ValueError("Excessive FtD packet length segments")
        if header_length % 7 or cursor + header_length + length > len(data):
            raise ValueError("Invalid FtD packet bounds")
        header, start = data[cursor : cursor + header_length], cursor + header_length
        cursor = start + length
        entries = []
        for i in range(0, header_length, 7):
            key = int.from_bytes(header[i : i + 3], "little")
            raw = header[i + 3 : i + 7]
            offset = int.from_bytes(raw[2:4] + raw[:2], "little")
            if offset > length or (entries and offset < entries[-1][1]):
                raise ValueError("Invalid FtD packet header offset")
            entries.append((key, offset))
        headers = {}
        for i, (key, offset) in enumerate(entries):
            if key in headers:
                raise ValueError("Duplicate FtD packet header")
            end = entries[i + 1][1] if i + 1 < len(entries) else length
            headers[key] = data[start + offset : start + end]
        yield identifier, headers, unsorted


def fields(data):
    result, cursor = {}, 0
    while cursor < len(data):
        if cursor + 3 > len(data):
            raise ValueError("Truncated FtD field")
        key, size = struct.unpack_from("<HB", data, cursor)
        cursor += 3
        if cursor + size > len(data) or key in result:
            raise ValueError("Invalid FtD field bounds")
        result[key] = data[cursor : cursor + size]
        cursor += size
    return result


def decode_decoration(values, identifier, mimic=False):
    def unpack(key, fmt, default):
        raw = values.get(key)
        if raw is None:
            return default
        if len(raw) != struct.calcsize(fmt):
            raise ValueError("Invalid decoration field size")
        return struct.unpack(fmt, raw)

    raw = values.get(0, uuid.UUID("75ffb576-34c6-4dae-87a6-0f45d6482070").bytes_le)
    if len(raw) != 16:
        raise ValueError("Invalid decoration mesh GUID")
    scale = unpack(1, "<3f", (1, 1, 1))
    position = unpack(2, "<3f", (0, 0, 0))
    orientation = unpack(3, "<3f", (0, 0, 0))
    if (
        not np.isfinite((*scale, *position, *orientation)).all()
        or max(map(abs, (*scale, *position))) > 2048
        or min(map(abs, scale)) < 1e-5
    ):
        raise ValueError("Invalid decoration transform")
    return {
        "id": identifier,
        "mesh_guid": str(uuid.UUID(bytes_le=raw)),
        "scale": scale,
        "position": position,
        "orientation": orientation,
        "paint": 0 if mimic else unpack(4, "<i", (0,))[0],
        "tether": (0, 0, 0) if mimic else unpack(5, "<3i", (0, 0, 0)),
        "hide_original": False if mimic else bool(unpack(6, "<?", (False,))[0]),
        "material_guid": str(uuid.UUID(bytes_le=values.get(5 if mimic else 7, b"\0" * 16))),
    }


def read_decorations(encoded):
    records = []
    if not encoded:
        return records
    for identifier, headers, _ in packet_headers(encoded):
        if identifier != 291231:
            continue
        for key, value in headers.items():
            if key in (9999, 100000):
                continue
            if len(records) >= 5000:
                raise ValueError("Decoration packet exceeds 5,000 entries")
            records.append(decode_decoration(fields(value), key))
    return records
