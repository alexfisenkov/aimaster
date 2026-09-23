"""HTTP server for 127.0.0.1 that starts without a reverse DNS lookup.

``http.server.HTTPServer.server_bind`` calls ``socket.getfqdn(host)`` only to
fill ``server_name``.  On a machine whose resolver is slow for 127.0.0.1
(seen on macOS CI runners: more than 25 seconds) that lookup blocks the
start of the Studio server, the Mini App gateway and the setup page.  The
name is never used by these handlers, so the bound address stands in for it.

On Windows ``SO_REUSEADDR`` means something else than on POSIX: it lets a
*second* process bind the very same port and steal connections.  There the
server binds with ``SO_EXCLUSIVEADDRUSE`` instead; POSIX is unchanged.
"""

from __future__ import annotations

import os
import socket
import socketserver
from http.server import ThreadingHTTPServer

_IS_WINDOWS = os.name == "nt"
# winsock.h: #define SO_EXCLUSIVEADDRUSE ((int)(~SO_REUSEADDR))
_SO_EXCLUSIVEADDRUSE = getattr(socket, "SO_EXCLUSIVEADDRUSE", ~socket.SO_REUSEADDR)


class LoopbackThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        if _IS_WINDOWS:
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, _SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port
