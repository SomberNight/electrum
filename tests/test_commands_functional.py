import asyncio
import base64
import os
import os.path
import subprocess
import sys
from typing import Sequence
import unittest

from aiorpcx import run_in_thread

from electrum import bitcoin
from electrum.wallet import restore_wallet_from_text
from electrum.simple_config import SimpleConfig
from electrum.util import json_decode, async_timeout, profiler
from electrum.logging import get_logger
from electrum.network import Network

from . import ElectrumTestCase


_logger = get_logger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
assert os.path.exists(os.path.join(PROJECT_ROOT, "run_electrum"))

from electrum.utils import stacktracer  # FIXME tmp
stacktracer.trace_start(os.path.join(PROJECT_ROOT, "trace.html"), interval=5)


class SubprocessErrored(Exception):
    def __init__(self, msg: str, *, stdout: str = None, stderr: str = None):
        super().__init__(msg)
        self.stdout = stdout
        self.stderr = stderr


async def exec_in_subprocess(commands: Sequence[str], *, timeout=15) -> str:
    def actual_exec():
        with subprocess.Popen(
            commands,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                kill_process(process)
                raise
            if process.returncode != 0:
                raise SubprocessErrored(
                    f"error executing command {process.args!r} ({process.returncode=}): {stderr=}. {stdout=}",
                    stdout=stdout,
                    stderr=stderr,
                )
            return stdout
    return await run_in_thread(actual_exec)


def kill_process(proc: subprocess.Popen):
    proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        if proc.poll() is not None:
            proc.kill()
    if proc.stdout:
        proc.stdout.close()
    if proc.stderr:
        proc.stderr.close()
    if proc.stdin:
        proc.stdin.close()


class SharedTestsMixin(ElectrumTestCase):
    __unittest_skip__ = True

    run_electrum_cmd: Sequence[str]

    def setUp(self):
        super().setUp()
        self.config = SimpleConfig({'electrum_path': self.electrum_path})
        self.python_exe = sys.executable
        assert self.python_exe  # check not None/empty

    async def load_wallet(self, *, path, password=None):
        return

    async def test_signmessage_handles_int_like_message_arg(self):
        wallet_path = os.path.join(self.electrum_path, "wallet1")
        restore_wallet_from_text("9dk", gap_limit=2, path=wallet_path, config=self.config)
        await self.load_wallet(path=wallet_path)
        address = "bcrt1qq2tmmcngng78nllq2pvrkchcdukemtj5jnxz44"
        message = "5"  # this should not be json-decoded to an int
        sig_base64 = await exec_in_subprocess([
            *self.run_electrum_cmd,
            "-w", wallet_path,
            "signmessage",
            address,
            message,
            "--password=",
        ])
        sig = base64.b64decode(sig_base64)
        verified = bitcoin.verify_usermessage_with_address(address, sig, message.encode('utf-8'))
        self.assertTrue(verified)

    async def test_argtype_txid_is_validated(self):
        wallet_path = os.path.join(self.electrum_path, "wallet1")
        restore_wallet_from_text("9dk", gap_limit=2, path=wallet_path, config=self.config)
        await self.load_wallet(path=wallet_path)
        for txid in ("{}", "deadbeefdeadbeef",):
            with self.assertRaises(SubprocessErrored) as cm:
                await exec_in_subprocess([
                    *self.run_electrum_cmd,
                    "-w", wallet_path,
                    "removelocaltx",
                    txid,
                    "--password=",
                ])
            self.assertIn(" is not a txid", cm.exception.stderr)



class TestOfflineCLI(SharedTestsMixin):
    __unittest_skip__ = False
    REGTEST = True

    def setUp(self):
        super().setUp()
        self.run_electrum_cmd = (
            self.python_exe,
            "./run_electrum",
            "--regtest",
            f"--dir={self.electrum_path}",
            "-o",
        )


class TestDaemonCLI(SharedTestsMixin):
    __unittest_skip__ = False
    REGTEST = True

    def setUp(self):
        super().setUp()
        self.run_electrum_cmd = (
            self.python_exe,
            "./run_electrum",
            "--regtest",
            f"--dir={self.electrum_path}",
        )

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # launch daemon
        self.daemon_process = subprocess.Popen(
            [
                *self.run_electrum_cmd,
                "daemon",
                "-v",
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )
        # wait until daemon is responsive
        try:
            async with async_timeout(60):
                while True:
                    try:
                        await exec_in_subprocess(
                            [*self.run_electrum_cmd, "getinfo"])
                    except SubprocessErrored as exc:
                        #_logger.warning(f"heyheyhey1. got {exc=}")
                        if (dret := self.daemon_process.poll()) is not None:  # check if daemon exited
                            stdout, stderr = self.daemon_process.communicate()
                            raise SubprocessErrored(
                                f"daemon exited ({dret=}): {stderr=}. {stdout=}", stdout=stdout, stderr=stderr,
                            )
                        await asyncio.sleep(0.1)
                    else:
                        break
        except asyncio.TimeoutError:
            #self._test_lock.release()
            raise

    @profiler(min_threshold=1)
    async def asyncTearDown(self):
        try:
            # TODO sending "stop" via RPC would be much faster probably
            await exec_in_subprocess([*self.run_electrum_cmd, "stop"], timeout=1)
        except (SubprocessErrored, subprocess.TimeoutExpired) as exc:
            pass
        kill_process(self.daemon_process)
        await super().asyncTearDown()

    async def load_wallet(self, *, path, password=None):
        password = password or ""
        await exec_in_subprocess([
            *self.run_electrum_cmd,
            "load_wallet",
            "-w", path,
            f"--password={password}",
        ])

    async def test_sanity_check_daemon_running(self):
        getinfo_str = await exec_in_subprocess([
            *self.run_electrum_cmd,
            "getinfo",
        ])
        getinfo = json_decode(getinfo_str)
        self.assertTrue(getinfo["auto_connect"])

    async def test_foo222(self):
        wallet_path = os.path.join(self.electrum_path, "wallet1")
        restore_wallet_from_text("9dk", gap_limit=2, path=wallet_path, config=self.config)
        await self.load_wallet(path=wallet_path)


class TestDaemonRPC:

    async def test_foo333(self):
        # "getinfo"
        await Network.async_send_http_on_proxy(
            "post", "http://user:passwd@127.0.0.1:7777",
            body=b"""{"jsonrpc": "2.0", "id": "1", "method": "getinfo"}""",
            #body=b"""{"jsonrpc": "2.0", "id": "1", "method": "getinfo", "params": %s }""",
        )

