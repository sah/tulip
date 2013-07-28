#!/usr/bin/env python3
"""TCP echo server example."""
import argparse
import tulip
try:
    import signal
except ImportError:
    signal = None


class EchoServer(tulip.Protocol):

    TIMEOUT = 5.0

    def __init__(self, transport):
        self.transport = transport
        self.transport.register_protocol(self)

        # start 5 seconds timeout timer
        self.h_timeout = tulip.get_event_loop().call_later(
            self.TIMEOUT, self.timeout)

    def timeout(self):
        print('connection timeout, closing.')
        self.transport.close()

    def data_received(self, data):
        print('data received: ', data.decode())
        self.transport.write(b'Re: ' + data)

        # restart timeout timer
        self.h_timeout.cancel()
        self.h_timeout = tulip.get_event_loop().call_later(
            self.TIMEOUT, self.timeout)

    def eof_received(self):
        pass

    def connection_lost(self, exc):
        print('connection lost:', exc)
        self.h_timeout.cancel()


class EchoClient(tulip.Protocol):

    message = 'This is the message. It will be echoed.'

    def __init__(self, transport):
        self.transport = transport
        self.transport.register_protocol(self)
        self.transport.write(self.message.encode())
        print('data sent:', self.message)

    def data_received(self, data):
        print('data received:', data)

        # disconnect after 10 seconds
        tulip.get_event_loop().call_later(10.0, self.transport.close)

    def eof_received(self):
        pass

    def connection_lost(self, exc):
        print('connection lost:', exc)
        tulip.get_event_loop().stop()


@tulip.task
def start_client(loop, host, port):
    transport = yield from loop.create_connection(host, port)
    EchoClient(transport)


@tulip.task
def start_server(loop, host, port):
    x = yield from loop.start_serving(EchoServer, host, port)
    print('serving on', x[0].getsockname())


ARGS = argparse.ArgumentParser(description="TCP Echo example.")
ARGS.add_argument(
    '--server', action="store_true", dest='server',
    default=False, help='Run tcp server')
ARGS.add_argument(
    '--client', action="store_true", dest='client',
    default=False, help='Run tcp client')
ARGS.add_argument(
    '--host', action="store", dest='host',
    default='127.0.0.1', help='Host name')
ARGS.add_argument(
    '--port', action="store", dest='port',
    default=9999, type=int, help='Port number')


if __name__ == '__main__':
    args = ARGS.parse_args()

    if ':' in args.host:
        args.host, port = args.host.split(':', 1)
        args.port = int(port)

    if (not (args.server or args.client)) or (args.server and args.client):
        print('Please specify --server or --client\n')
        ARGS.print_help()
    else:
        loop = tulip.get_event_loop()
        if signal is not None:
            loop.add_signal_handler(signal.SIGINT, loop.stop)

        if args.server:
            loop.run_until_complete(start_server(loop, args.host, args.port))
        else:
            loop.run_until_complete(start_client(loop, args.host, args.port))

        loop.run_forever()
