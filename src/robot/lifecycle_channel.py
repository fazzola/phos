"""Bounded local process channel for application lifecycle operations."""
from threading import Lock


class LifecycleClient:
    def __init__(self, connection):
        self.connection = connection
        self.lock = Lock()
        self.available = True

    def execute(self, operation):
        if not isinstance(operation, str) or operation not in {"status", "reload", "restart"}:
            return {"ok": False, "error": "Unsupported lifecycle operation."}
        with self.lock:
            if not self.available:
                return self._unavailable()
            try:
                self.connection.send(operation)
                if not self.connection.poll(5):
                    # Retiring the channel avoids interpreting a late reply as
                    # the response to a different operation.
                    self.available = False
                    return self._unavailable()
                return self.connection.recv()
            except (OSError, EOFError):
                self.available = False
                return self._unavailable()

    @staticmethod
    def _unavailable():
        return {"ok": False, "error": "Runtime lifecycle service is unavailable. An in-flight request may have completed; check PHOS locally before retrying."}


def serve_lifecycle(connection, service, stop):
    try:
        while not stop.is_set():
            if connection.poll(.2):
                operation = connection.recv()
                result = service.execute(operation)
                connection.send(result)
    except (EOFError, OSError):
        pass
    finally:
        connection.close()
