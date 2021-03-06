#!/usr/bin/env python3
"""Simple multiprocess http server written using an event loop."""

import argparse
import email.message
import os
import socket
import signal
import time
import tulip
import tulip.http
from tulip.http import websocket

ARGS = argparse.ArgumentParser(description="Run simple http server.")
ARGS.add_argument(
    '--host', action="store", dest='host',
    default='127.0.0.1', help='Host name')
ARGS.add_argument(
    '--port', action="store", dest='port',
    default=8080, type=int, help='Port number')
ARGS.add_argument(
    '--workers', action="store", dest='workers',
    default=2, type=int, help='Number of workers.')


class HttpServer(tulip.http.ServerHttpProtocol):

    @tulip.coroutine
    def handle_request(self, message, payload):
        print('{}: method = {!r}; path = {!r}; version = {!r}'.format(
            os.getpid(), message.method, message.path, message.version))

        path = message.path

        if (not (path.isprintable() and path.startswith('/')) or '/.' in path):
            path = None
        else:
            path = '.' + path
            if not os.path.exists(path):
                path = None
            else:
                isdir = os.path.isdir(path)

        if not path:
            raise tulip.http.HttpStatusException(404)

        headers = email.message.Message()
        for hdr, val in message.headers:
            headers.add_header(hdr, val)

        if isdir and not path.endswith('/'):
            path = path + '/'
            raise tulip.http.HttpStatusException(
                302, headers=(('URI', path), ('Location', path)))

        response = tulip.http.Response(self.transport, 200)
        response.add_header('Transfer-Encoding', 'chunked')

        # content encoding
        accept_encoding = headers.get('accept-encoding', '').lower()
        if 'deflate' in accept_encoding:
            response.add_header('Content-Encoding', 'deflate')
            response.add_compression_filter('deflate')
        elif 'gzip' in accept_encoding:
            response.add_header('Content-Encoding', 'gzip')
            response.add_compression_filter('gzip')

        response.add_chunking_filter(1025)

        if isdir:
            response.add_header('Content-type', 'text/html')
            response.send_headers()

            response.write(b'<ul>\r\n')
            for name in sorted(os.listdir(path)):
                if name.isprintable() and not name.startswith('.'):
                    try:
                        bname = name.encode('ascii')
                    except UnicodeError:
                        pass
                    else:
                        if os.path.isdir(os.path.join(path, name)):
                            response.write(b'<li><a href="' + bname +
                                           b'/">' + bname + b'/</a></li>\r\n')
                        else:
                            response.write(b'<li><a href="' + bname +
                                           b'">' + bname + b'</a></li>\r\n')
            response.write(b'</ul>')
        else:
            response.add_header('Content-type', 'text/plain')
            response.send_headers()

            try:
                with open(path, 'rb') as fp:
                    chunk = fp.read(8196)
                    while chunk:
                        response.write(chunk)
                        chunk = fp.read(8196)
            except OSError:
                response.write(b'Cannot open')

        response.write_eof()
        if response.keep_alive():
            self.keep_alive(True)


class ChildProcess:

    def __init__(self, up_read, down_write, args, sock):
        self.up_read = up_read
        self.down_write = down_write
        self.args = args
        self.sock = sock

    def start(self):
        # start server
        self.loop = loop = tulip.new_event_loop()
        tulip.set_event_loop(loop)

        def stop():
            self.loop.stop()
            os._exit(0)
        loop.add_signal_handler(signal.SIGINT, stop)

        f = loop.start_serving(
            lambda tr: HttpServer(tr, debug=True, keep_alive=75),
            sock=self.sock)
        x = loop.run_until_complete(f)[0]
        print('Starting srv worker process {} on {}'.format(
            os.getpid(), x.getsockname()))

        # heartbeat
        self.heartbeat()

        tulip.get_event_loop().run_forever()
        os._exit(0)

    @tulip.task
    def heartbeat(self):
        # setup pipes
        read_transport = yield from self.loop.connect_read_pipe(
            os.fdopen(self.up_read, 'rb'))
        read_proto = tulip.StreamProtocol(read_transport)
        write_transport = yield from self.loop.connect_write_pipe(
            os.fdopen(self.down_write, 'wb'))
        write_proto = tulip.StreamProtocol(write_transport)

        reader = read_proto.set_parser(websocket.WebSocketParser())
        writer = websocket.WebSocketWriter(write_transport)

        while True:
            msg = yield from reader.read()
            if msg is None:
                print('Superviser is dead, {} stopping...'.format(os.getpid()))
                self.loop.stop()
                break
            elif msg.tp == websocket.MSG_PING:
                writer.pong()
            elif msg.tp == websocket.MSG_CLOSE:
                break

        read_transport.close()
        write_transport.close()


class Worker:

    _started = False

    def __init__(self, loop, args, sock):
        self.loop = loop
        self.args = args
        self.sock = sock
        self.start()

    def start(self):
        assert not self._started
        self._started = True

        up_read, up_write = os.pipe()
        down_read, down_write = os.pipe()
        args, sock = self.args, self.sock

        pid = os.fork()
        if pid:
            # parent
            os.close(up_read)
            os.close(down_write)
            self.connect(pid, up_write, down_read)
        else:
            # child
            os.close(up_write)
            os.close(down_read)

            # cleanup after fork
            tulip.set_event_loop(None)

            # setup process
            process = ChildProcess(up_read, down_write, args, sock)
            process.start()

    @tulip.task
    def heartbeat(self, writer):
        while True:
            yield from tulip.sleep(15)

            if (time.monotonic() - self.ping) < 30:
                writer.ping()
            else:
                print('Restart unresponsive worker process: {}'.format(
                    self.pid))
                self.kill()
                self.start()
                return

    @tulip.task
    def chat(self, reader):
        while True:
            msg = yield from reader.read()
            if msg is None:
                print('Restart unresponsive worker process: {}'.format(
                    self.pid))
                self.kill()
                self.start()
                return
            elif msg.tp == websocket.MSG_PONG:
                self.ping = time.monotonic()

    @tulip.task
    def connect(self, pid, up_write, down_read):
        # setup pipes
        read_transport = yield from self.loop.connect_read_pipe(
            os.fdopen(down_read, 'rb'))
        read_proto = tulip.StreamProtocol(read_transport)
        write_transport = yield from self.loop.connect_write_pipe(
            os.fdopen(up_write, 'wb'))
        write_proto = tulip.StreamProtocol(write_transport)

        # websocket protocol
        reader = read_proto.set_parser(websocket.WebSocketParser())
        writer = websocket.WebSocketWriter(write_transport)

        # store info
        self.pid = pid
        self.ping = time.monotonic()
        self.rtransport = read_transport
        self.wtransport = write_transport
        self.chat_task = self.chat(reader)
        self.heartbeat_task = self.heartbeat(writer)

    def kill(self):
        self._started = False
        self.chat_task.cancel()
        self.heartbeat_task.cancel()
        self.rtransport.close()
        self.wtransport.close()
        os.kill(self.pid, signal.SIGTERM)


class Superviser:

    def __init__(self, args):
        self.loop = tulip.get_event_loop()
        self.args = args
        self.workers = []

    def start(self):
        # bind socket
        sock = self.sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.args.host, self.args.port))
        sock.listen(1024)
        sock.setblocking(False)

        # start processes
        for idx in range(self.args.workers):
            self.workers.append(Worker(self.loop, self.args, sock))

        self.loop.add_signal_handler(signal.SIGINT, lambda: self.loop.stop())
        self.loop.run_forever()


def main():
    args = ARGS.parse_args()
    if ':' in args.host:
        args.host, port = args.host.split(':', 1)
        args.port = int(port)

    superviser = Superviser(args)
    superviser.start()


if __name__ == '__main__':
    main()
