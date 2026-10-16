import asyncio
import struct

import pytest
from pymodbus.client import AsyncModbusTcpClient
from quayside_components.modbus import ModbusServer, ModbusUnit, Table, WriteRejected
from quayside_components.modbus.server import ExceptionCode, Function


def exception_code(response: bytes) -> int:
    assert response[0] & 0x80, response  # Check if error bit is set
    return response[1]


@pytest.fixture
def server():
    unit = ModbusUnit(coils=10, discrete_inputs=3, holding_registers=4, input_registers=5)
    unit.set_input_registers([10, 20, 30, 40, 50])
    unit.set_discrete_inputs([True, False, True])

    return ModbusServer({1: unit})


def test_read_input_registers(server):
    pdu = struct.pack(">BHH", Function.READ_INPUT_REGISTERS, 1, 3)
    response = server.process(1, pdu)

    assert response == bytes([4, 6]) + struct.pack(">3H", 20, 30, 40)


def test_read_discrete_inputs_pack_bits(server):
    pdu = struct.pack(">BHH", Function.READ_DISCRETE_INPUTS, 0, 3)
    response = server.process(1, pdu)

    assert response == bytes([2, 1, 0b101])


@pytest.mark.parametrize(
    ("pdu", "code"),
    [
        (struct.pack(">BHH", Function.READ_INPUT_REGISTERS, 4, 2), ExceptionCode.ILLEGAL_DATA_ADDRESS),
        (struct.pack(">BHH", Function.READ_INPUT_REGISTERS, 0, 0), ExceptionCode.ILLEGAL_DATA_VALUE),
        (struct.pack(">BHH", Function.READ_HOLDING_REGISTERS, 0, 126), ExceptionCode.ILLEGAL_DATA_VALUE),
        (struct.pack(">BHH", Function.WRITE_SINGLE_COIL, 0, 0x1234), ExceptionCode.ILLEGAL_DATA_VALUE),
        (bytes([0x2B, 0x0E, 0x01, 0x00]), ExceptionCode.ILLEGAL_FUNCTION),
        (bytes([Function.READ_COILS]), ExceptionCode.ILLEGAL_DATA_VALUE),
    ],
)
def test_protocol_errors(server, pdu, code):
    response = server.process(1, pdu)
    assert exception_code(response) == code


def test_unknown_unit_is_gateway_error(server):
    pdu = struct.pack(">BHH", Function.READ_COILS, 0, 1)
    response = server.process(42, pdu)

    assert exception_code(response) == ExceptionCode.GATEWAY_TARGET_FAILED


def test_write_hook_can_reject():
    seen = []

    def hook(table, address, values):
        seen.append((table, address, list(values)))

        if any(v > 100 for v in values):
            raise WriteRejected

    unit = ModbusUnit(holding_registers=2, on_write=hook)
    server = ModbusServer({1: unit})

    ok_pdu = struct.pack(">BHH", Function.WRITE_SINGLE_REGISTER, 1, 42)
    ok_response = server.process(1, ok_pdu)

    assert ok_response[0] == Function.WRITE_SINGLE_REGISTER

    rejected_pdu = struct.pack(">BHH", Function.WRITE_SINGLE_REGISTER, 0, 500)
    rejected_response = server.process(1, rejected_pdu)

    assert exception_code(rejected_response) == ExceptionCode.ILLEGAL_DATA_VALUE
    assert unit.holding_registers == [0, 42]
    assert seen == [(Table.HOLDING_REGISTERS, 1, [42]), (Table.HOLDING_REGISTERS, 0, [500])]


def test_interoperates_with_pymodbus_client(server):
    async def scenario():
        async with server:
            client = AsyncModbusTcpClient("127.0.0.1", port=server.port, timeout=1, retries=0)
            assert await client.connect()

            try:
                regs = await client.read_input_registers(0, count=5, device_id=1)
                await client.write_coils(2, [True, False, True, True], device_id=1)
                await client.write_registers(0, [7, 8, 9], device_id=1)
                coils = await client.read_coils(0, count=10, device_id=1)
                bad = await client.write_registers(3, [1, 2], device_id=1)

            finally:
                client.close()

            return regs.registers, coils.bits[:10], bad

    unit = server.units[1]
    server.host, server.port = "127.0.0.1", 0
    registers, coils, bad = asyncio.run(scenario())

    assert registers == [10, 20, 30, 40, 50]
    assert coils == [False, False, True, False, True, True, False, False, False, False]
    assert unit.holding_registers == [7, 8, 9, 0]
    assert bad.isError() and bad.exception_code == ExceptionCode.ILLEGAL_DATA_ADDRESS
