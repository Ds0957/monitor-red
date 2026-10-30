"""ICMP echo through the Windows IP Helper API (IcmpSendEcho).

Unlike the `ping` command, this needs no output parsing (which is localized on
Windows) and no administrator rights. Only importable on Windows.
"""

from __future__ import annotations

import ctypes
import socket
import struct
from ctypes import wintypes

_iphlpapi = ctypes.WinDLL("iphlpapi.dll", use_last_error=True)

IP_SUCCESS = 0
_PAYLOAD = b"monitor-red-ping" * 2  # 32 bytes, like the default ping


class _IPOptionInformation(ctypes.Structure):
    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p),
    ]


class _IcmpEchoReply(ctypes.Structure):
    _fields_ = [
        ("Address", wintypes.ULONG),
        ("Status", wintypes.ULONG),
        ("RoundTripTime", wintypes.ULONG),
        ("DataSize", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("Data", ctypes.c_void_p),
        ("Options", _IPOptionInformation),
    ]


_IcmpCreateFile = _iphlpapi.IcmpCreateFile
_IcmpCreateFile.restype = wintypes.HANDLE
_IcmpCreateFile.argtypes = []

_IcmpCloseHandle = _iphlpapi.IcmpCloseHandle
_IcmpCloseHandle.restype = wintypes.BOOL
_IcmpCloseHandle.argtypes = [wintypes.HANDLE]

_IcmpSendEcho = _iphlpapi.IcmpSendEcho
_IcmpSendEcho.restype = wintypes.DWORD
_IcmpSendEcho.argtypes = [
    wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.WORD,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
]

_INVALID_HANDLE = wintypes.HANDLE(-1).value


def ping(ip: str, timeout: float = 1.0) -> float | None:
    """Send one echo request; return the round-trip time in ms, or None if no reply."""
    # IPAddr is the address in network byte order, read as a native ULONG.
    address = struct.unpack("<I", socket.inet_aton(ip))[0]
    handle = _IcmpCreateFile()
    if not handle or handle == _INVALID_HANDLE:
        raise OSError(ctypes.get_last_error(), "IcmpCreateFile failed")
    try:
        size = ctypes.sizeof(_IcmpEchoReply) + len(_PAYLOAD) + 8 + 64
        buffer = ctypes.create_string_buffer(size)
        payload = ctypes.create_string_buffer(_PAYLOAD, len(_PAYLOAD))
        count = _IcmpSendEcho(handle, address, payload, len(_PAYLOAD), None, buffer, size,
                              max(1, int(timeout * 1000)))
        if count == 0:
            return None
        reply = _IcmpEchoReply.from_buffer(buffer)
        if reply.Status != IP_SUCCESS:
            return None
        return float(reply.RoundTripTime)
    finally:
        _IcmpCloseHandle(handle)
