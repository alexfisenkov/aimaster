"""Provider GET security contract; deterministic sockets, no external traffic."""
import io
import socket
import ssl
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.provider_download import fetch_original, original_url, preflight


class VideoPreflightTests(unittest.TestCase):
    def test_magnific_video_requires_both_local_media_tools_before_network(self):
        route = {'provider':'magnific','position_id':'pos:scene:s1:video'}
        with patch('studio.platform_compat.find_program', side_effect=lambda name: None if name == 'ffmpeg' else '/bin/ffprobe'), \
             patch('studio.provider_download._addresses') as dns:
            self.assertFalse(preflight(route))
            dns.assert_not_called()
        with patch('studio.platform_compat.find_program', side_effect=lambda name: None if name == 'ffprobe' else '/bin/ffmpeg'), \
             patch('studio.provider_download._addresses') as dns:
            self.assertFalse(preflight(route))
            dns.assert_not_called()


class Socket:
    def __init__(self,response):
        self.response=response; self.connected=[]; self.sent=[]; self.timeouts=[]
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def settimeout(self,value): self.timeouts.append(value)
    def connect(self,address): self.connected.append(address)
    def sendall(self,data): self.sent.append(data)
    def makefile(self,*args): return io.BytesIO(self.response)


class OriginalDownloadTests(unittest.TestCase):
    artifact={"url":"https://pikaso.cdnpk.net/private/original.png?signature=private", "mime_type":"image/png", "size_bytes":None}
    def fetch(self,response,addresses=None,**kw):
        edge=Socket(response)
        addresses=addresses or [(socket.AF_INET,socket.SOCK_STREAM,6,"",("1.1.1.1",443))]
        with patch("socket.getaddrinfo",return_value=addresses),patch("socket.socket",return_value=edge) as sockets,patch("ssl.create_default_context") as context:
            context.return_value.wrap_socket.return_value=edge
            result=fetch_original("magnific",{**self.artifact,**kw})
            self.assertEqual(sockets.call_count,1)
            context.return_value.wrap_socket.assert_called_once_with(edge,server_hostname="pikaso.cdnpk.net")
        return result,edge

    def test_numeric_public_resolution_is_pinned_and_tls_hostname_preserved(self):
        data,edge=self.fetch(b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: 3\r\n\r\nPNG")
        self.assertEqual(data,b"PNG")
        self.assertEqual(edge.connected,[("1.1.1.1",443)])
        self.assertTrue(all(0<t<=30 for t in edge.timeouts))
        self.assertTrue(edge.sent[0].startswith(b"GET /private/original.png?signature=private HTTP/1.1"))
        self.assertNotIn(b"Authorization",edge.sent[0]); self.assertNotIn(b"Cookie",edge.sent[0])

    def test_redirect_content_type_oversize_and_incomplete_response_refuse(self):
        for response in (
            b"HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/private\r\nContent-Length: 0\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 3\r\n\r\nbad",
            b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: 999999999\r\n\r\n",
        ):
            with self.subTest(response=response[:30]),self.assertRaises(ValueError) as error:
                self.fetch(response)
            self.assertNotIn("signature",str(error.exception))
        with patch("studio.provider_download.MAX_BYTES",3),self.assertRaises(ValueError):
            self.fetch(b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n\r\nLONG")

    def test_all_private_and_mapped_dns_answers_refuse_before_connect(self):
        for address in ("127.0.0.1","10.2.3.4","169.254.169.254","::1","::ffff:127.0.0.1","fe80::1","ff02::1"):
            rows=[(socket.AF_INET6 if ':' in address else socket.AF_INET,socket.SOCK_STREAM,6,"",(address,443))]
            with self.subTest(address=address),patch("socket.getaddrinfo",return_value=rows),patch("socket.socket") as connect:
                with self.assertRaises(ValueError):fetch_original("magnific",self.artifact)
                connect.assert_not_called()

    def test_mixed_system_dns_pins_only_public_answer(self):
        rows=[(socket.AF_INET6,socket.SOCK_STREAM,6,"",("fd00:aa:bb::1",443,0,0)),
              (socket.AF_INET,socket.SOCK_STREAM,6,"",("1.1.1.1",443))]
        data,edge=self.fetch(b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: 3\r\n\r\nPNG",addresses=rows)
        self.assertEqual(data,b"PNG")
        self.assertEqual(edge.connected,[("1.1.1.1",443)])

    def test_unknown_origin_auth_ports_paths_and_provider_swaps_are_refused(self):
        for url in ("http://pikaso.cdnpk.net/private/a", "https://pikaso.cdnpk.net.evil.invalid/private/a",
                    "https://user@pikaso.cdnpk.net/private/a", "https://pikaso.cdnpk.net:444/private/a",
                    "https://pikaso.cdnpk.net/private/%2e%2e/a", "https://pikaso.cdnpk.net/public/a",
                    "https://pikaso.cdnpk.net/private/a#secret", "https://pikaso.cdnpk.net/private/a\r\nX:yes"):
            with self.subTest(url=url),self.assertRaises(ValueError):original_url("magnific",url)
        with self.assertRaises(ValueError):original_url("syntx",self.artifact["url"])
        self.assertEqual(original_url("syntx","https://r2.syntx.ai/owner/original.png").hostname,"r2.syntx.ai")
        self.assertEqual(original_url("fal","https://v3b.fal.media/files/original.png").hostname,"v3b.fal.media")


if __name__ == "__main__": unittest.main()
