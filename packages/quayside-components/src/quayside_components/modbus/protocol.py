import struct
from collections.abc import Sequence
from enum import IntEnum

MBAP_HEADER = struct.Struct(">HHHB")
MAX_PDU = 253


class Function(IntEnum):
    READ_COILS = 0x01
    READ_DISCRETE_INPUTS = 0x02
    READ_HOLDING_REGISTERS = 0x03
    READ_INPUT_REGISTERS = 0x04
    WRITE_SINGLE_COIL = 0x05
    WRITE_SINGLE_REGISTER = 0x06
    WRITE_MULTIPLE_COILS = 0x0F
    WRITE_MULTIPLE_REGISTERS = 0x10


class ExceptionCode(IntEnum):
    ILLEGAL_FUNCTION = 0x01
    ILLEGAL_DATA_ADDRESS = 0x02
    ILLEGAL_DATA_VALUE = 0x03
    SERVER_DEVICE_FAILURE = 0x04
    GATEWAY_TARGET_FAILED = 0x0B


def pack_bits(bits: Sequence[bool]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)

    for i, bit in enumerate(bits):
        if bit:
            out[i // 8] |= 1 << (i % 8)

    return bytes(out)


def unpack_bits(data: bytes, count: int) -> list[bool]:
    return [bool(data[i // 8] >> (i % 8) & 1) for i in range(count)]
