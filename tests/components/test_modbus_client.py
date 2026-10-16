import asyncio
import time

import pytest
from quayside_components.modbus import (
    ModbusClient,
    ModbusError,
    ModbusExceptionResponse,
    ModbusServer,
    ModbusUnit,
)
from quayside_components.modbus.protocol import ExceptionCode


async def with_server(unit, body):
    server = ModbusServer({3: unit}, host="127.0.0.1", port=0)
    await server.start()

    async with server, ModbusClient("127.0.0.1", server.port) as client:
        return await body(client)


def test_roundtrip_against_server():
    unit = ModbusUnit(coils=5, discrete_inputs=2, holding_registers=3, input_registers=2)
    unit.set_input_registers([1, 65535])
    unit.set_discrete_inputs([False, True])

    async def body(client):
        await client.write_coils(1, [True, True, False, True], unit=3)
        await client.write_coil(0, True, unit=3)
        await client.write_registers(0, [11, 12], unit=3)
        await client.write_register(2, 13, unit=3)

        return (
            await client.read_coils(0, 5, unit=3),
            await client.read_discrete_inputs(0, 2, unit=3),
            await client.read_holding_registers(0, 3, unit=3),
            await client.read_input_registers(0, 2, unit=3),
        )

    coils, inputs, holding, registers = asyncio.run(with_server(unit, body))

    assert coils == [True, True, True, False, True]
    assert inputs == [False, True]
    assert holding == [11, 12, 13]
    assert registers == [1, 65535]


def test_exception_response_keeps_connection():
    unit = ModbusUnit(input_registers=1)

    async def body(client):
        with pytest.raises(ModbusExceptionResponse) as e:
            await client.read_input_registers(0, 10, unit=3)

        assert e.value.code == ExceptionCode.ILLEGAL_DATA_ADDRESS
        assert client.connected

        with pytest.raises(ModbusExceptionResponse) as e:
            await client.read_input_registers(0, 1, unit=9)

        assert e.value.code == ExceptionCode.GATEWAY_TARGET_FAILED
        return await client.read_input_registers(0, 1, unit=3)

    assert asyncio.run(with_server(unit, body)) == [0]


def test_timeout_closes_connection():
    async def silent(reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        await reader.read()  # Never answers anything

    async def body():
        server = await asyncio.start_server(silent, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async with server, ModbusClient("127.0.0.1", port, timeout=0.2) as client:
            started = time.monotonic()

            with pytest.raises(ModbusError, match="timed out"):
                await client.read_coils(0, 1)

            assert 0.2 <= time.monotonic() - started < 0.5
            assert not client.connected

    asyncio.run(body())


def test_connection_refused():
    async def body():
        async with ModbusClient("127.0.0.1", port=1, timeout=0.5) as client:
            with pytest.raises(ModbusError):
                await client.read_coils(0, 1)

    asyncio.run(body())
