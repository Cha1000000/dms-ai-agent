"""Shared bridge-test helper: raw-fd line reading.

select() on a text-mode pipe is unreliable: the BufferedReader may already
have swallowed the next lines into its userspace buffer, so the fd looks
idle while data sits in Python's buffer (seen as rare bridge-test flakes).
Reading the raw fd and splitting lines ourselves is deterministic.
"""
import json
import os
import select
import time


class LineReader:
    def __init__(self, stream):
        self.fd = stream.fileno()
        self.buf = b""

    def read_event(self, timeout=10):
        deadline = time.time() + timeout
        while True:
            if b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                try:
                    return json.loads(line.decode())
                except ValueError:
                    continue
            if time.time() > deadline:
                return None
            r, _, _ = select.select([self.fd], [], [], 0.3)
            if not r:
                continue
            chunk = os.read(self.fd, 65536)
            if not chunk:
                return None
            self.buf += chunk


def read_event(reader, timeout=10):
    if isinstance(reader, LineReader):
        return reader.read_event(timeout)
    return LineReader(reader).read_event(timeout)
