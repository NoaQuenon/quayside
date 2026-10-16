import asyncio
import struct
from collections.abc import Sequence

from quayside_components.modbus.protocol import (
    MAX_PDU,
    MBAP_HEADER,
    ExceptionCode,
    Function,
    pack_bits,
    unpack_bits,
)


class ModbusError(ExceptionCode):
    """Raised when a transport or protocol failure occurs and the connection has been closed"""


class ModbusExceptionResponse(ModbusError):
    """Raised when the server answered with a Modbus exception"""

    def __init__(self, function: int, code: int):
        try:
            name = ExceptionCode(code).name

        except ValueError:
            name = f"0x{code:02x}"

        super().__init__(f"function 0x{function:02x} failed: {name}")

        self.function = function
        self.code = code


class ModbusClient:
    def __init__(self, host: str, port: int = 502, timeout: float = 1):
        self.host = host
        self.port = port
        self.timeout = timeout

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._transaction = 0
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        if not self.connected:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()

        self._reader = self._writer = None

    async def __aenter__(self) -> ModbusClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.close()

    async def read_coils(self, address: int, count: int, unit: int = 1) -> list[bool]:
        return await self._read_bits(Function.READ_COILS, address, count, unit)

    async def read_discrete_inputs(self, address: int, count: int, unit: int = 1) -> list[bool]:
        return await self._read_bits(Function.READ_DISCRETE_INPUTS, address, count, unit)

    async def read_holding_registers(self, address: int, count: int, unit: int = 1) -> list[int]:
        return await self._read_registers(Function.READ_HOLDING_REGISTERS, address, count, unit)

    async def read_input_registers(self, address: int, count: int, unit: int = 1) -> list[int]:
        return await self._read_registers(Function.READ_INPUT_REGISTERS, address, count, unit)

    async def write_coil(self, address: int, value: bool, unit: int = 1) -> None:
        pdu = struct.pack(">BHH", Function.WRITE_SINGLE_COIL, address, 0xFF00 if value else 0)
        await self._transact(unit, pdu)

    async def write_register(self, address: int, value: int, unit: int = 1) -> None:
        pdu = struct.pack(">BHH", Function.WRITE_SINGLE_REGISTER, address, value)
        await self._transact(unit, pdu)

    async def write_coils(self, address: int, values: Sequence[bool], unit: int = 1) -> None:
        packed = pack_bits(values)
        pdu = struct.pack(">BHHB", Function.WRITE_MULTIPLE_COILS, address, len(values), len(packed)) + packed

        await self._transact(unit, pdu)

    async def write_registers(self, address: int, values: Sequence[int], unit: int = 1) -> None:
        count = len(values)
        pdu = struct.pack(
            f">BHHB{count}H", Function.WRITE_MULTIPLE_REGISTERS, address, count, 2 * count, *values
        )

        await self._transact(unit, pdu)

    async def _read_bits(self, function: Function, address: int, count: int, unit: int) -> list[bool]:
        pdu = struct.pack(">BHH", function, address, count)
        response = await self._transact(unit, pdu)

        if not response or response[0] != len(response) - 1 or response[0] < (count + 7) // 8:
            self._fail("malformed bit read response")

        return unpack_bits(response[1:], count)

    async def _read_registers(self, function: Function, address: int, count: int, unit: int) -> list[int]:
        pdu = struct.pack(">BHH", function, address, count)
        response = await self._transact(unit, pdu)

        if not response or response[0] != 2 * count or len(response) != 1 + 2 * count:
            self._fail("malformed register read response")

        return list(struct.unpack(f">{count}H", response[1:]))

    async def _transact(self, unit: int, pdu: bytes) -> bytes:
        async with self._lock:
            try:
                return await asyncio.wait_for(self._exchange(unit, pdu), self.timeout)

            except ModbusExceptionResponse:
                raise

            except TimeoutError:
                self.close()
                raise ModbusError(f"{self.host}:{self.port}: timed out after {self.timeout}s") from None

            except (OSError, asyncio.IncompleteReadError) as e:
                self.close()
                raise ModbusError(f"{self.host}:{self.port}: {e}") from e

    async def _exchange(self, unit: int, pdu: bytes) -> bytes:
        await self.connect()
        assert self._reader is not None and self._writer is not None

        self._transaction = (self._transaction + 1) & 0xFFFF
        tid = self._transaction
        packet = MBAP_HEADER.pack(tid, 0, len(pdu) + 1, unit) + pdu
        self._writer.write(packet)
        await self._writer.drain()

        header = await self._reader.readexactly(MBAP_HEADER.size)
        rtid, protocol, length, runit = MBAP_HEADER.unpack(header)

        if protocol != 0 or not 2 <= length <= MAX_PDU + 1:
            self._fail("malformed MBAP header")

        response = await self._reader.readexactly(length - 1)

        if rtid != tid or runit != unit:
            self._fail(f"response for transaction {rtid}/unit {runit}, expected {tid}/{unit}")

        function = response[0]

        if function == pdu[0] | 0x80:
            raise ModbusExceptionResponse(pdu[0], response[1] if len(response) > 1 else 0)

        if function != pdu[0]:
            self._fail(f"response function 0x{function:02x} to request 0x{pdu[0]:02x}")

        return response[1:]

    def _fail(self, message: str) -> None:
        self.close()
        raise ModbusError(f"{self.host}:{self.port}: {message}")
