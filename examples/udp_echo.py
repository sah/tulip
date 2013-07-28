#!/usr/bin/env python3
"""UDP echo example."""
import argparse
import sys
import tulip
try:
    import signal
except ImportError:
    signal = None


class MyServerUdpEchoProtocol:

    def __init__(self, transport):
        print('start', transport)
        self.transport = transport
        self.transport.register_protocol(self)

    def datagram_received(self, data, addr):
        print('Data received:', data, addr)
        self.transport.sendto(data, addr)

    def connection_refused(self, exc):
        print('Connection refused:', exc)

    def connection_lost(self, exc):
        print('stop', exc)


class MyClientUdpEchoProtocol:

    message = 'This is the message. It will be echoed.'

    def __init__(self, transport):
        self.transport = transport
        self.transport.register_protocol(self)
        print('sending "{}"'.format(self.message))
        self.transport.sendto(self.message.encode())
        print('waiting to receive')

    def datagram_received(self, data, addr):
        print('received "{}"'.format(data.decode()))
        self.transport.close()

    def connection_refused(self, exc):
        print('Connection refused:', exc)

    def connection_lost(self, exc):
        print('closing transport', exc)
        loop = tulip.get_event_loop()
        loop.stop()


@tulip.task
def start_server(loop, addr):
    tr = yield from loop.create_datagram_endpoint(local_addr=addr)
    MyServerUdpEchoProtocol(tr)


@tulip.task
def start_client(loop, addr):
    tr = yield from loop.create_datagram_endpoint(remote_addr=addr)
    MyClientUdpEchoProtocol(tr)


ARGS = argparse.ArgumentParser(description="UDP Echo example.")
ARGS.add_argument(
    '--server', action="store_true", dest='server',
    default=False, help='Run udp server')
ARGS.add_argument(
    '--client', action="store_true", dest='client',
    default=False, help='Run udp client')
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

        if '--server' in sys.argv:
            loop.run_until_complete(start_server(loop, (args.host, args.port)))
        else:
            loop.run_until_complete(start_client(loop, (args.host, args.port)))

        loop.run_forever()
