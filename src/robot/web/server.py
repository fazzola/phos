"""Separate-process WSGI lifecycle; no web dependencies when disabled."""
from __future__ import annotations

import multiprocessing
from pathlib import Path


def _serve(path, active, connection):
    server = None
    try:
        from waitress import create_server
        from robot.web.app import create_app
        app = create_app(Path(path), active_document=active)
        server = create_server(app, host=active["web"]["host"], port=active["web"]["port"],
                               threads=2, connection_limit=32, channel_timeout=30,
                               max_request_body_size=64 * 1024, max_request_header_size=8192,
                               expose_tracebacks=False, clear_untrusted_proxy_headers=True)
        connection.send(None)
        connection.close()
        server.run()
    except Exception as error:
        # Send only type information: exception messages may contain local data.
        try:
            connection.send(type(error).__name__)
        except (OSError, EOFError):
            pass
    finally:
        connection.close()
        if server is not None:
            server.close()


class WebServer:
    """Own one isolated worker and always release its port on PHOS exit.

    Termination can interrupt a request; both configuration and credential writes
    use atomic replacement. Sessions and rate limits intentionally reset on restart.
    """
    def __init__(self, config_path, config):
        self.path = str(Path(config_path).resolve())
        self.config = config
        self.process = None

    def __enter__(self):
        if not self.config.web_enabled:
            return self
        context = multiprocessing.get_context("spawn")
        reader, writer = context.Pipe(duplex=False)
        self.process = context.Process(target=_serve, args=(self.path, self.config.to_dict(), writer),
                                       name="phos-admin", daemon=True)
        try:
            self.process.start()
            writer.close()
            if not reader.poll(30):
                raise RuntimeError("Web administration startup timed out")
            error = reader.recv()
            if error is not None:
                raise RuntimeError(f"Web administration failed ({error}); check web dependencies, port and .phos-admin permissions")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        finally:
            reader.close()
            writer.close()
        return self

    def __exit__(self, *_):
        if self.process is not None and self.process.pid is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=5)
            self.process.close()
            self.process = None
