"""Запись ответа `http_app.Response` в сокет — одна на оба сервера (дашборд
и шлюз Mini App). Тело — либо байты (`body`), либо поток (`stream`: файл
кусками, `asset_stream.FileBody`). Content-Length ставится ровно один раз, по
настоящей длине тела; заголовок с таким именем из самого ответа (его ставит,
например, `MiniAppGateway._rewrite_asset_urls`) не повторяется: два разных
Content-Length — недопустимая разметка (RFC 9112 §6.3), туннель Mini App её
отвергает. Поток закрывается всегда — и после HEAD, и при обрыве."""

from __future__ import annotations


def write_response(handler, response) -> None:
    stream = response.stream
    try:
        handler.send_response(response.status)
        for name, value in response.headers.items():
            if name.casefold() != "content-length":
                handler.send_header(name, value)
        length = stream.length if stream is not None else len(response.body)
        handler.send_header("Content-Length", str(length))
        handler.end_headers()
        if handler.command == "HEAD":
            return
        if stream is None:
            handler.wfile.write(response.body)
            return
        for chunk in stream.chunks():
            handler.wfile.write(chunk)
    finally:
        if stream is not None:
            stream.close()
