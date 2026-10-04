"""A single persistent asyncio owner for Telegram and all mutable service state."""
import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeout
from copy import deepcopy
import logging
import threading
import time
import uuid

from tg_forwarder.tasks.errors import OperationError, RuntimeUnavailable

logger = logging.getLogger(__name__)


class RuntimeBridge:
    def __init__(self, factory, timeout=15):
        self.factory = factory
        self.timeout = timeout
        self._thread = None
        self._loop = None
        self._service = None
        self._ready = Future()
        self._stop = None
        self._accepting = False
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._submission_lock = threading.Lock()
        self._requests = set()

    def start(self):
        if self._thread is not None:
            raise RuntimeError("RuntimeBridge may only be started once")
        self._thread = threading.Thread(target=self._run, name="forwarder-runtime", daemon=True)
        self._thread.start()
        try:
            self._ready.result(timeout=self.timeout)
        except BaseException:
            self.stop()
            raise
        return self

    def _run(self):
        try:
            asyncio.run(self._main())
        except BaseException as error:
            if not self._ready.done():
                self._ready.set_exception(error)
            else:
                logger.exception("Forwarding runtime exited")
        finally:
            self._accepting = False

    async def _main(self):
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._service = self.factory()
        try:
            await self._service.start_background()
            self._accepting = True
            self._ready.set_result(None)
            await self._stop.wait()
            with self._submission_lock:
                self._accepting = False
                requests = list(self._requests)
            # Include submitted calls even if their coroutine has not started.
            if requests:
                await asyncio.gather(*(asyncio.wrap_future(future) for future in requests), return_exceptions=True)
        finally:
            await self._service.shutdown()

    async def _invoke(self, operation, params, context):
        asyncio.current_task().set_name("runtime-request")
        return deepcopy(await self._service.invoke(operation, params, **context))

    def call(self, operation, params=None, **context):
        if threading.current_thread() is self._thread:
            raise RuntimeError("RuntimeBridge.call cannot block its own event loop")
        with self._submission_lock:
            if not self._accepting:
                raise RuntimeUnavailable()
            future = asyncio.run_coroutine_threadsafe(self._invoke(operation, params or {}, context), self._loop)
            self._requests = {entry for entry in self._requests if not entry.done()}
            self._requests.add(future)
        try:
            return future.result(timeout=self.timeout)
        except FutureTimeout:
            if future.done():
                return future.result()
            if operation.startswith("auth."):
                raise RuntimeUnavailable("认证服务响应超时，请稍后重试")
            # HTTP timeout is not task cancellation. Retain the result for polling.
            key = uuid.uuid4().hex
            now = time.monotonic()
            with self._pending_lock:
                self._pending = {key: entry for key, entry in self._pending.items()
                    if not entry[0].done() or now - entry[2] < 300}
                self._pending[key] = (future, context.get("token"), now)
            return {"pending": True, "operation_id": key}

    def result(self, key, token):
        with self._pending_lock:
            entry = self._pending.get(key)
        if entry is None or entry[1] != token:
            raise OperationError("operation_not_found", "操作记录不存在", 404)
        if not entry[0].done():
            return {"pending": True, "operation_id": key}
        return {"pending": False, "result": deepcopy(entry[0].result())}

    def stop(self):
        with self._submission_lock:
            self._accepting = False
            if self._loop and self._stop and self._thread and self._thread.is_alive():
                self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=60)
            if self._thread.is_alive():
                raise RuntimeError("Forwarding runtime has not finished shutdown")

    @property
    def alive(self):
        return bool(self._thread and self._thread.is_alive())
