"""HTTP server for 127.0.0.1 that starts without a reverse DNS lookup.

``http.server.HTTPServer.server_bind`` calls ``socket.getfqdn(host)`` only to
fill ``server_name``.  On a machine whose resolver is slow for 127.0.0.1
(seen on macOS CI runners: more than 25 seconds) that lookup blocks the
start of the Studio server, the Mini App gateway and the setup page.  The
name is never used by these handlers, so the bound address stands in for it.
"""

from __future__ import annotations

import socketserver
from http.server import ThreadingHTTPServer


class LoopbackThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port
