# Copyright (C) 2026 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php

import asyncio
import concurrent.futures
import copy
from collections import defaultdict
from typing import (
     Callable, Sequence, Dict, Set,
)
import threading
from functools import partial
import inspect

from .logging import get_logger, Logger
from .util import get_asyncio_loop, run_sync_function_on_asyncio_thread


_logger = get_logger(__name__)


class CallbackManager(Logger):
    # callbacks set by the GUI or any thread
    # guarantee: the callbacks will always get triggered from the asyncio thread.

    # FIXME: There should be a way to prevent circular callbacks.
    # At the very least, we need a distinction between callbacks that
    # are for the GUI and callbacks between wallet components

    def __init__(self):
        Logger.__init__(self)
        self.callback_lock = threading.Lock()
        self.callbacks = defaultdict(set)  # type: Dict[str, Set[Callable]]  # note: needs self.callback_lock

    def register_callback(self, func: Callable, events: Sequence[str]) -> None:
        with self.callback_lock:
            for event in events:
                self.callbacks[event].add(func)

    def unregister_callback(self, callback: Callable) -> None:
        with self.callback_lock:
            for callbacks in self.callbacks.values():
                if callback in callbacks:
                    callbacks.remove(callback)

    def clear_all_callbacks(self) -> None:
        with self.callback_lock:
            self.callbacks.clear()

    def trigger_callback(self, event: str, *args) -> None:
        """Trigger a callback with given arguments.
        Can be called from any thread. The callback itself will get scheduled
        on the event loop.
        """
        loop = get_asyncio_loop()
        assert loop.is_running(), "event loop not running"
        with self.callback_lock:
            callbacks = copy.copy(self.callbacks[event])
        for callback in callbacks:
            if inspect.iscoroutinefunction(callback):  # async cb
                fut = asyncio.run_coroutine_threadsafe(callback(*args), loop)

                def on_done(fut_: concurrent.futures.Future):
                    assert fut_.done()
                    if fut_.cancelled():
                        self.logger.debug(f"cb cancelled. {event=}.")
                    elif exc := fut_.exception():
                        self.logger.error(f"cb errored. {event=}. {exc=}", exc_info=exc)
                fut.add_done_callback(on_done)
            else:  # non-async cb
                run_sync_function_on_asyncio_thread(partial(callback, *args), block=False)


_INSTANCE = CallbackManager()
trigger_callback = _INSTANCE.trigger_callback
register_callback = _INSTANCE.register_callback
unregister_callback = _INSTANCE.unregister_callback
_event_listeners = defaultdict(set)  # type: Dict[str, Set[str]]


class EventListener:
    """Use as a mixin for a class that has methods to be triggered on events.
    - Methods that receive the callbacks should be named "on_event_*" and decorated with @event_listener.
    - register_callbacks() should be called once per instance of EventListener, e.g. in __init__
    - unregister_callbacks() should be called at least once, e.g. when the instance is destroyed
        - if register_callbacks() is called in __init__, as opposed to a separate start() method,
          extra care is needed that the call to unregister_callbacks() is not forgotten,
          otherwise we will leak memory
    """

    def _list_callbacks(self):
        for c in self.__class__.__mro__:
            classpath = f"{c.__module__}.{c.__name__}"
            for method_name in _event_listeners[classpath]:
                method = getattr(self, method_name)
                assert callable(method)
                assert method_name.startswith('on_event_')
                yield method_name[len('on_event_'):], method

    def register_callbacks(self):
        for name, method in self._list_callbacks():
            #_logger.debug(f'registering callback {method}')
            register_callback(method, [name])

    def unregister_callbacks(self):
        for name, method in self._list_callbacks():
            #_logger.debug(f'unregistering callback {method}')
            unregister_callback(method)


def event_listener(func):
    """To be used in subclasses of EventListener only. (how to enforce this programmatically?)"""
    classname, method_name = func.__qualname__.split('.')
    assert method_name.startswith('on_event_')
    classpath = f"{func.__module__}.{classname}"
    _event_listeners[classpath].add(method_name)
    return func
