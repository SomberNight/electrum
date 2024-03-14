import asyncio
import sys
import unittest

import aiorpcx

import electrum.util as util

from . import ElectrumTestCase


class TestAsyncio(ElectrumTestCase):

    async def test_aiorpcx_timeoutafter_composability(self):
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
        # ...
        with self.subTest("asyncio.ensure_future"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await asyncio.ensure_future(foo())
        with self.subTest("asyncio.create_task"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await asyncio.create_task(foo())


class TestAiorpcxTimeoutAfterComposability(ElectrumTestCase):

    @staticmethod
    async def foo(*, timeout=0.001):
        async with aiorpcx.timeout_after(timeout):
            await asyncio.sleep(10)

    async def test_no_nesting(self):
        with self.assertRaises(aiorpcx.TaskTimeout):
            await self.foo()

    @unittest.skipIf(sys.version_info[:3] < (3, 11), "broken on old python")
    async def test_asyncio_wait_for(self):
        with self.subTest("timeout=None. internal timeout"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await asyncio.wait_for(self.foo(), None)
        with self.subTest("timeout=2. internal timeout"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await asyncio.wait_for(self.foo(), 2)
        with self.subTest("external timeout"):
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(self.foo(timeout=2), 0.001)

    async def test_util_wait_for2(self):
        with self.subTest("timeout=None. internal timeout"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await util.wait_for2(self.foo(), None)
        with self.subTest("timeout=2. internal timeout"):
            with self.assertRaises(aiorpcx.TaskTimeout):
                await util.wait_for2(self.foo(), 2)
        with self.subTest("external timeout"):
            with self.assertRaises(asyncio.TimeoutError):
                await util.wait_for2(self.foo(timeout=2), 0.001)

    @unittest.skipIf(sys.version_info[:3] < (3, 11), "broken on old python")
    async def test_ensure_future(self):
        with self.assertRaises(aiorpcx.TaskTimeout):
            await asyncio.ensure_future(self.foo())

    @unittest.skipIf(sys.version_info[:3] < (3, 11), "broken on old python")
    async def test_create_task(self):
        with self.assertRaises(aiorpcx.TaskTimeout):
            await asyncio.create_task(self.foo())
