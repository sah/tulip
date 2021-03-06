# NOTE: This is a hack.  Andrew Svetlov is working in a proper
# subprocess management transport for use with
# connect_{read,write}_pipe().

"""Tests for subprocess_transport.py."""

import logging
import unittest

from tulip import events
from tulip import futures
from tulip import protocols
from tulip import subprocess_transport


class MyProto(protocols.Protocol):

    def __init__(self, transport):
        self.state = 'INITIAL'
        self.nbytes = 0
        self.done = futures.Future()
        self.transport = transport
        assert self.state == 'INITIAL', self.state
        self.state = 'CONNECTED'
        transport.write_eof()
        transport.register_protocol(self)

    def data_received(self, data):
        logging.info('received: %r', data)
        assert self.state == 'CONNECTED', self.state
        self.nbytes += len(data)

    def eof_received(self):
        assert self.state == 'CONNECTED', self.state
        self.state = 'EOF'
        self.transport.close()

    def connection_lost(self, exc):
        assert self.state in ('CONNECTED', 'EOF'), self.state
        self.state = 'CLOSED'
        self.done.set_result(None)


class FutureTests(unittest.TestCase):

    def setUp(self):
        self.loop = events.new_event_loop()
        events.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_unix_subprocess(self):
        tr = subprocess_transport.UnixSubprocessTransport(['/bin/ls', '-lR'])
        p = MyProto(tr)
        self.loop.run_until_complete(p.done)


if __name__ == '__main__':
    unittest.main()
