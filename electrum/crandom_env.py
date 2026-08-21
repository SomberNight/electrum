# Copyright (C) 2026 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php
#
# This module is a companion to crandom.py and is only intended to be accessed from there.

import os
import platform
import socket
import ssl
import sys
import threading
import time
from typing import TYPE_CHECKING, Callable

from .logging import get_logger

if TYPE_CHECKING:
    from .crandom import CRANDOM_FEEDER_API


_logger = get_logger(__name__)


def _safe_feed(do_feed: Callable[[], None]) -> None:
    try:
        do_feed()
    except (AttributeError, OSError) as e:
        _logger.debug(f"skipping an entropy source due to error: {e!r}")


def rand_add_static_env(feed: 'CRANDOM_FEEDER_API') -> None:
    """Gather non-cryptographic environment data that does not change over time
    and feed it into feed().
    """
    # os
    feed(str(os.environ))
    _safe_feed(lambda: feed(os.ctermid()))
    _safe_feed(lambda: feed(os.getcwd()))
    _safe_feed(lambda: feed(str(os.get_exec_path())))
    _safe_feed(lambda: feed(str(os.getgroups())))
    _safe_feed(lambda: feed(str(os.getlogin())))
    _safe_feed(lambda: feed(os.getpgrp()))
    _safe_feed(lambda: feed(os.getpid()))
    _safe_feed(lambda: feed(os.getppid()))
    _safe_feed(lambda: feed(str(os.getresuid())))
    _safe_feed(lambda: feed(str(os.getresgid())))
    _safe_feed(lambda: feed(str(os.uname())))
    # timezone
    feed(time.timezone)
    feed(str(time.tzname))
    # system locale
    import locale
    feed(str(locale.getlocale()))
    # mac address
    from uuid import getnode as get_mac_address
    feed(get_mac_address())
    # hostname
    _safe_feed(lambda: feed(socket.gethostname()))
    # threading
    _safe_feed(lambda: feed(threading.get_native_id()))
    feed(str(threading.enumerate()))
    # platform
    from .logging import describe_os_version
    feed(sys.version)
    feed(platform.platform())
    feed(describe_os_version())
    # version of electrum
    from . import ELECTRUM_VERSION
    from .logging import get_git_version
    feed(ELECTRUM_VERSION)
    #feed(get_git_version() or "")  # skipping for now as resolving "git" from $PATH might open up its own issues
    # path to this file
    feed(__file__)
    # memory locations
    feed(id(__file__))
    feed(id(id))
    feed(id(os))
    feed(id(feed))
    feed(id(ELECTRUM_VERSION))
    feed(id(_logger))
    feed(id("longish_string_literal"))
    feed(id(0))

def rand_add_dynamic_env(feed: 'CRANDOM_FEEDER_API') -> None:
    """Gather non-cryptographic environment data that changes over time and feed it into feed()."""
    # time
    feed(time.time_ns())
    feed(time.process_time_ns())
    feed(time.perf_counter_ns())
    # openssl
    try:
        feed(ssl.RAND_bytes(32))
    except ssl.SSLError as e:
        _logger.info(f"failed to get randomness from ssl: {e!r}")
