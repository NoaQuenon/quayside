import asyncio
import logging
import struct
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum

from quayside_components.modbus.protocol import (
    MAX_PDU,
    MBAP_HEADER,
    ExceptionCode,
    Function,
    pack_bits,
    unpack_bits,
)

log = logging.getLogger(__name__)


class Table(StrEnum):
    COILS = "coils"
    DISCRETE_INPUTS = "discrete_inputs"
    HOLDING_REGISTERS = "holding_registers"
    INPUT_REGISTERS = "input_registers"


class WriteRejected(Exception):
    """Raised by a write hook to answer the client with ILLEGAL_DATA_VALUE (cf. functions below)"""


WriteHook = Callable[[Table, int, Sequence[int] | Sequence[bool]], None]


class ModbusUnit:
    def __init__(
        self,
        coils: int = 0,
        discrete_inputs: int = 0,
        holding_registers: int = 0,
        input_registers: int = 0,
        on_write: WriteHook | None = None,
    ):
        self.coils = [False] * coils
        self.discrete_inputs = [False] * discrete_inputs
        self.holding_registers = [0] * holding_registers
        self.input_registers = [0] * input_registers
        self.on_write = on_write

    def table(self, table: Table) -> list:
        return getattr(self, table.value)

    def set_coils(self, values: Sequence[bool], address: int = 0) -> None:
        _store(self.coils, address, [bool(v) for v in values])

    def set_discrete_inputs(self, values: Sequence[bool], address: int = 0) -> None:
        _store(self.discrete_inputs, address, [bool(v) for v in values])

    def set_holding_registers(self, values: Sequence[int], address: int = 0) -> None:
        _store(self.holding_registers, address, [_u16(v) for v in values])

    def set_input_registers(self, values: Sequence[int], address: int = 0) -> None:
        _store(self.input_registers, address, [_u16(v) for v in values])


def _u16(value: int) -> int:
    return max(0, min(0xFFFF, int(value)))


def _store(target: list, address: int, values: list) -> None:
    if address < 0 or address + len(values) > len(target):
        raise IndexError(f"write of {len(values)} values at {address} exceeds table size {len(target)}")

    target[address : address + len(values)] = values


class _ModbusError(Exception):
    def __init__(self, code: ExceptionCode):
        self.code = code


class ModbusServer:
    def __init__(self, units: Mapping[int, ModbusUnit], host: str = "0.0.0.0", port: int = 502):
        self.units = dict(units)
        self.host = host
        self.port = port

        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        if self._server is not None:
            # Server is already started
            return

        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        sockets = self._server.sockets or ()

        if sockets and self.port == 0:
            # Find the port assigned by the kernel
            self.port = sockets[0].getsockname()[1]

        log.info("modbus server listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()

            for writer in list(self._connections):
                writer.close()

            await self._server.wait_closed()
            self._server = None

    async def __aenter__(self) -> ModbusServer:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.debug("connection from %s", peer)
        self._connections.add(writer)

        try:
            while True:
                header = await reader.readexactly(MBAP_HEADER.size)
                tid, protocol, length, unit_id = MBAP_HEADER.unpack(header)

                if protocol != 0 or not 2 <= length <= MAX_PDU + 1:
                    log.warning("malformed MBAP header from %s; closing", peer)
                    return

                pdu = await reader.readexactly(length - 1)
                response = self.process(unit_id, pdu)
                writer.write(MBAP_HEADER.pack(tid, 0, len(response) + 1, unit_id) + response)

                await writer.drain()

        except asyncio.IncompleteReadError, ConnectionError:
            pass

        finally:
            self._connections.discard(writer)
            writer.close()

    def process(self, unit_id: int, pdu: bytes) -> bytes:
        function = pdu[0]

        try:
            unit = self.units.get(unit_id)

            if unit is None:
                raise _ModbusError(ExceptionCode.GATEWAY_TARGET_FAILED)

            return bytes([function]) + self._dispatch(unit, function, pdu[1:])

        except _ModbusError as e:
            return bytes([function | 0x80, e.code])

        except Exception:
            log.exception("error handling function 0x%02x", function)
            return bytes([function | 0x80, ExceptionCode.SERVER_DEVICE_FAILURE])

    def _dispatch(self, unit: ModbusUnit, function: int, body: bytes) -> bytes:
        match function:
            case Function.READ_COILS | Function.READ_DISCRETE_INPUTS:
                table = Table.COILS if function == Function.READ_COILS else Table.DISCRETE_INPUTS
                address, count = _unpack(">HH", body)
                values = _read(unit.table(table), address, count, 2000)
                packed = pack_bits(values)

                return bytes([len(packed)]) + packed

            case Function.READ_HOLDING_REGISTERS | Function.READ_INPUT_REGISTERS:
                table = (
                    Table.HOLDING_REGISTERS
                    if function == Function.READ_HOLDING_REGISTERS
                    else Table.INPUT_REGISTERS
                )

                address, count = _unpack(">HH", body)
                values = _read(unit.table(table), address, count, 125)

                return bytes([2 * count]) + struct.pack(f">{count}H", *values)

            case Function.WRITE_SINGLE_COIL:
                address, raw = _unpack(">HH", body)

                if raw not in (0x0000, 0xFF00):
                    raise _ModbusError(ExceptionCode.ILLEGAL_DATA_VALUE)

                _write(unit, Table.COILS, address, [raw == 0xFF00])

                return body[:4]

            case Function.WRITE_SINGLE_REGISTER:
                address, value = _unpack(">HH", body)
                _write(unit, Table.HOLDING_REGISTERS, address, [value])

                return body[:4]

            case Function.WRITE_MULTIPLE_COILS:
                address, count, nbytes = _unpack(">HHB", body)

                # Weird bounds because of the packing
                if not 1 <= count <= 1968 or nbytes != (count + 7) // 8 or len(body) < 5 + nbytes:
                    raise _ModbusError(ExceptionCode.ILLEGAL_DATA_VALUE)

                _write(unit, Table.COILS, address, unpack_bits(body[5 : 5 + nbytes], count))

                return body[:4]

            case Function.WRITE_MULTIPLE_REGISTERS:
                address, count, nbytes = _unpack(">HHB", body)

                if not 1 <= count <= 123 or nbytes != 2 * count or len(body) < 5 + nbytes:
                    raise _ModbusError(ExceptionCode.ILLEGAL_DATA_VALUE)

                values = list(struct.unpack(f">{count}H", body[5 : 5 + nbytes]))
                _write(unit, Table.HOLDING_REGISTERS, address, values)

                return body[:4]

            case _:
                raise _ModbusError(ExceptionCode.ILLEGAL_FUNCTION)


def _unpack(fmt: str, body: bytes) -> tuple[int, ...]:
    size = struct.calcsize(fmt)

    if len(body) < size:
        raise _ModbusError(ExceptionCode.ILLEGAL_DATA_VALUE)

    return struct.unpack(fmt, body[:size])


def _read(table: list, address: int, count: int, max_count: int) -> list:
    if not 1 <= count <= max_count:
        raise _ModbusError(ExceptionCode.ILLEGAL_DATA_VALUE)

    if address + count > len(table):
        raise _ModbusError(ExceptionCode.ILLEGAL_DATA_ADDRESS)

    return table[address : address + count]


def _write(unit: ModbusUnit, table: Table, address: int, values: list) -> None:
    target = unit.table(table)

    if address + len(values) > len(target):
        raise _ModbusError(ExceptionCode.ILLEGAL_DATA_ADDRESS)

    if unit.on_write is not None:
        try:
            unit.on_write(table, address, values)

        except WriteRejected:
            raise _ModbusError(ExceptionCode.ILLEGAL_DATA_VALUE) from None

    target[address : address + len(values)] = values
