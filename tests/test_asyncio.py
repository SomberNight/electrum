import asyncio

import aiorpcx

import electrum.util as util

from . import ElectrumTestCase


class TestAsyncio(ElectrumTestCase):

    async def test_waitfor_vs_timeoutafter(self):
        async def foo(*, timeout=0.001):
            async with aiorpcx.timeout_after(timeout):
                await asyncio.sleep(10)
        with self.assertRaises(aiorpcx.TaskTimeout):
            await foo()
        # asyncio.wait_for
        with self.subTest("asyncio.wait_for(timeout=None) - internal timeout"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await asyncio.wait_for(foo(), None)
        with self.subTest("asyncio.wait_for(timeout=2) - internal timeout"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await asyncio.wait_for(foo(), 2)
        with self.subTest("asyncio.wait_for(...) - external timeout"):
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(foo(timeout=2), 0.001)
        # util.wait_for2
        with self.subTest("util.wait_for2(timeout=None) - internal timeout"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await util.wait_for2(foo(), None)
        with self.subTest("util.wait_for2(timeout=2) - internal timeout"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await util.wait_for2(foo(), 2)
        with self.subTest("util.wait_for2(...) - external timeout"):
            with self.assertRaises(asyncio.TimeoutError):
                await util.wait_for2(foo(timeout=2), 0.001)
