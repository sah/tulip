"""Tests for base_events.py"""

import logging
import socket
import time
import unittest
import unittest.mock

from tulip import base_events
from tulip import events
from tulip import futures
from tulip import protocols
from tulip import tasks
from tulip import test_utils


class BaseEventLoopTests(unittest.TestCase):

    def setUp(self):
        self.loop = base_events.BaseEventLoop()
        self.loop._selector = unittest.mock.Mock()
        self.loop._selector.registered_count.return_value = 1
        events.set_event_loop(self.loop)

    def test_not_implemented(self):
        m = unittest.mock.Mock()
        self.assertRaises(
            NotImplementedError,
            self.loop._make_socket_transport, m, m)
        self.assertRaises(
            NotImplementedError,
            self.loop._make_ssl_transport, m, m, m)
        self.assertRaises(
            NotImplementedError,
            self.loop._make_datagram_transport, m, m)
        self.assertRaises(
            NotImplementedError, self.loop._process_events, [])
        self.assertRaises(
            NotImplementedError, self.loop._write_to_self)
        self.assertRaises(
            NotImplementedError, self.loop._read_from_self)
        self.assertRaises(
            NotImplementedError,
            self.loop._make_read_pipe_transport, m, m)
        self.assertRaises(
            NotImplementedError,
            self.loop._make_write_pipe_transport, m, m)

    def test__add_callback_handle(self):
        h = events.Handle(lambda: False, ())

        self.loop._add_callback(h)
        self.assertFalse(self.loop._scheduled)
        self.assertIn(h, self.loop._ready)

    def test__add_callback_timer(self):
        h = events.TimerHandle(time.monotonic()+10, lambda: False, ())

        self.loop._add_callback(h)
        self.assertIn(h, self.loop._scheduled)

    def test__add_callback_cancelled_handle(self):
        h = events.Handle(lambda: False, ())
        h.cancel()

        self.loop._add_callback(h)
        self.assertFalse(self.loop._scheduled)
        self.assertFalse(self.loop._ready)

    def test_set_default_executor(self):
        executor = unittest.mock.Mock()
        self.loop.set_default_executor(executor)
        self.assertIs(executor, self.loop._default_executor)

    def test_getnameinfo(self):
        sockaddr = unittest.mock.Mock()
        self.loop.run_in_executor = unittest.mock.Mock()
        self.loop.getnameinfo(sockaddr)
        self.assertEqual(
            (None, socket.getnameinfo, sockaddr, 0),
            self.loop.run_in_executor.call_args[0])

    def test_call_soon(self):
        def cb():
            pass

        h = self.loop.call_soon(cb)
        self.assertEqual(h._callback, cb)
        self.assertIsInstance(h, events.Handle)
        self.assertIn(h, self.loop._ready)

    def test_call_later(self):
        def cb():
            pass

        h = self.loop.call_later(10.0, cb)
        self.assertIsInstance(h, events.TimerHandle)
        self.assertIn(h, self.loop._scheduled)
        self.assertNotIn(h, self.loop._ready)

    def test_call_later_negative_delays(self):
        calls = []

        def cb(arg):
            calls.append(arg)

        self.loop._process_events = unittest.mock.Mock()
        self.loop.call_later(-1, cb, 'a')
        self.loop.call_later(-2, cb, 'b')
        test_utils.run_briefly(self.loop)
        self.assertEqual(calls, ['b', 'a'])

    def test_time_and_call_at(self):
        def cb():
            self.loop.stop()

        self.loop._process_events = unittest.mock.Mock()
        when = self.loop.time() + 0.1
        self.loop.call_at(when, cb)
        t0 = self.loop.time()
        self.loop.run_forever()
        t1 = self.loop.time()
        self.assertTrue(0.09 <= t1-t0 <= 0.12, t1-t0)

    def test_run_once_in_executor_handle(self):
        def cb():
            pass

        self.assertRaises(
            AssertionError, self.loop.run_in_executor,
            None, events.Handle(cb, ()), ('',))
        self.assertRaises(
            AssertionError, self.loop.run_in_executor,
            None, events.TimerHandle(10, cb, ()))

    def test_run_once_in_executor_cancelled(self):
        def cb():
            pass
        h = events.Handle(cb, ())
        h.cancel()

        f = self.loop.run_in_executor(None, h)
        self.assertIsInstance(f, futures.Future)
        self.assertTrue(f.done())
        self.assertIsNone(f.result())

    def test_run_once_in_executor_plain(self):
        def cb():
            pass
        h = events.Handle(cb, ())
        f = futures.Future()
        executor = unittest.mock.Mock()
        executor.submit.return_value = f

        self.loop.set_default_executor(executor)

        res = self.loop.run_in_executor(None, h)
        self.assertIs(f, res)

        executor = unittest.mock.Mock()
        executor.submit.return_value = f
        res = self.loop.run_in_executor(executor, h)
        self.assertIs(f, res)
        self.assertTrue(executor.submit.called)

        f.cancel()  # Don't complain about abandoned Future.

    def test__run_once(self):
        h1 = events.TimerHandle(time.monotonic() + 0.1, lambda: True, ())
        h2 = events.TimerHandle(time.monotonic() + 10.0, lambda: True, ())

        h1.cancel()

        self.loop._process_events = unittest.mock.Mock()
        self.loop._scheduled.append(h1)
        self.loop._scheduled.append(h2)
        self.loop._run_once()

        t = self.loop._selector.select.call_args[0][0]
        self.assertTrue(9.99 < t < 10.1)
        self.assertEqual([h2], self.loop._scheduled)
        self.assertTrue(self.loop._process_events.called)

    def test__run_once_timeout(self):
        h = events.TimerHandle(time.monotonic() + 10.0, lambda: True, ())

        self.loop._process_events = unittest.mock.Mock()
        self.loop._scheduled.append(h)
        self.loop._run_once(1.0)
        self.assertEqual((1.0,), self.loop._selector.select.call_args[0])

    def test__run_once_timeout_with_ready(self):
        # If event loop has ready callbacks, select timeout is always 0.
        h = events.TimerHandle(time.monotonic() + 10.0, lambda: True, ())

        self.loop._process_events = unittest.mock.Mock()
        self.loop._scheduled.append(h)
        self.loop._ready.append(h)
        self.loop._run_once(1.0)

        self.assertEqual((0,), self.loop._selector.select.call_args[0])

    @unittest.mock.patch('tulip.base_events.time')
    @unittest.mock.patch('tulip.base_events.tulip_log')
    def test__run_once_logging(self, m_logging, m_time):
        # Log to INFO level if timeout > 1.0 sec.
        idx = -1
        data = [10.0, 10.0, 12.0, 13.0]

        def monotonic():
            nonlocal data, idx
            idx += 1
            return data[idx]

        m_time.monotonic = monotonic
        m_logging.INFO = logging.INFO
        m_logging.DEBUG = logging.DEBUG

        self.loop._scheduled.append(
            events.TimerHandle(11.0, lambda: True, ()))
        self.loop._process_events = unittest.mock.Mock()
        self.loop._run_once()
        self.assertEqual(logging.INFO, m_logging.log.call_args[0][0])

        idx = -1
        data = [10.0, 10.0, 10.3, 13.0]
        self.loop._scheduled = [events.TimerHandle(11.0, lambda:True, ())]
        self.loop._run_once()
        self.assertEqual(logging.DEBUG, m_logging.log.call_args[0][0])

    def test__run_once_schedule_handle(self):
        handle = None
        processed = False

        def cb(loop):
            nonlocal processed, handle
            processed = True
            handle = loop.call_soon(lambda: True)

        h = events.TimerHandle(time.monotonic() - 1, cb, (self.loop,))

        self.loop._process_events = unittest.mock.Mock()
        self.loop._scheduled.append(h)
        self.loop._run_once()

        self.assertTrue(processed)
        self.assertEqual([handle], list(self.loop._ready))

    def test_run_until_complete_type_error(self):
        self.assertRaises(
            TypeError, self.loop.run_until_complete, 'blah')


class MyProto(protocols.Protocol):
    done = None

    def __init__(self, transport, create_future=False):
        self.state = 'INITIAL'
        self.nbytes = 0
        if create_future:
            self.done = futures.Future()
        self.transport = transport
        assert self.state == 'INITIAL', self.state
        self.state = 'CONNECTED'
        transport.register_protocol(self)
        transport.write(b'GET / HTTP/1.0\r\nHost: example.com\r\n\r\n')

    def data_received(self, data):
        assert self.state == 'CONNECTED', self.state
        self.nbytes += len(data)

    def eof_received(self):
        assert self.state == 'CONNECTED', self.state
        self.state = 'EOF'
        self.transport.close()

    def connection_lost(self, exc):
        assert self.state in ('CONNECTED', 'EOF'), self.state
        self.state = 'CLOSED'
        if self.done:
            self.done.set_result(None)


class MyDatagramProto(protocols.DatagramProtocol):
    done = None

    def __init__(self, create_future=False):
        self.state = 'INITIAL'
        self.nbytes = 0
        if create_future:
            self.done = futures.Future()
        self.transport = transport
        assert self.state == 'INITIAL', self.state
        self.state = 'INITIALIZED'

    def datagram_received(self, data, addr):
        assert self.state == 'INITIALIZED', self.state
        self.nbytes += len(data)

    def connection_refused(self, exc):
        assert self.state == 'INITIALIZED', self.state

    def connection_lost(self, exc):
        assert self.state == 'INITIALIZED', self.state
        self.state = 'CLOSED'
        if self.done:
            self.done.set_result(None)


class BaseEventLoopWithSelectorTests(unittest.TestCase):

    def setUp(self):
        self.loop = events.new_event_loop()
        events.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    @unittest.mock.patch('tulip.base_events.socket')
    def test_create_connection_mutiple_errors(self, m_socket):

        class MyProto(protocols.Protocol):
            def __init__(self, transport):
                pass

        @tasks.coroutine
        def getaddrinfo(*args, **kw):
            yield from []
            return [(2, 1, 6, '', ('107.6.106.82', 80)),
                    (2, 1, 6, '', ('107.6.106.82', 80))]

        idx = -1
        errors = ['err1', 'err2']

        def _socket(*args, **kw):
            nonlocal idx, errors
            idx += 1
            raise socket.error(errors[idx])

        m_socket.socket = _socket
        m_socket.error = socket.error

        self.loop.getaddrinfo = getaddrinfo

        task = tasks.Task(
            self.loop.create_connection('example.com', 80))
        yield from tasks.wait(task)
        exc = task.exception()
        self.assertEqual("Multiple exceptions: err1, err2", str(exc))

    def test_create_connection_host_port_sock(self):
        coro = self.loop.create_connection('example.com', 80, sock=object())
        self.assertRaises(ValueError, self.loop.run_until_complete, coro)

    def test_create_connection_no_host_port_sock(self):
        coro = self.loop.create_connection()
        self.assertRaises(ValueError, self.loop.run_until_complete, coro)

    def test_create_connection_no_getaddrinfo(self):
        @tasks.task
        def getaddrinfo(*args, **kw):
            yield from []
        self.loop.getaddrinfo = getaddrinfo
        coro = self.loop.create_connection('example.com', 80)
        self.assertRaises(
            socket.error, self.loop.run_until_complete, coro)

    def test_create_connection_connect_err(self):
        @tasks.task
        def getaddrinfo(*args, **kw):
            yield from []
            return [(2, 1, 6, '', ('107.6.106.82', 80))]
        self.loop.getaddrinfo = getaddrinfo
        self.loop.sock_connect = unittest.mock.Mock()
        self.loop.sock_connect.side_effect = socket.error

        coro = self.loop.create_connection('example.com', 80)
        self.assertRaises(
            socket.error, self.loop.run_until_complete, coro)

    def test_create_connection_mutiple(self):
        @tasks.task
        def getaddrinfo(*args, **kw):
            return [(2, 1, 6, '', ('0.0.0.1', 80)),
                    (2, 1, 6, '', ('0.0.0.2', 80))]
        self.loop.getaddrinfo = getaddrinfo
        self.loop.sock_connect = unittest.mock.Mock()
        self.loop.sock_connect.side_effect = socket.error

        coro = self.loop.create_connection(
            'example.com', 80, family=socket.AF_INET)
        with self.assertRaises(socket.error):
            self.loop.run_until_complete(coro)

    @unittest.mock.patch('tulip.base_events.socket')
    def test_create_connection_mutiple_errors_local_addr(self, m_socket):
        m_socket.error = socket.error

        def bind(addr):
            if addr[0] == '0.0.0.1':
                err = socket.error('Err')
                err.strerror = 'Err'
                raise err

        m_socket.socket.return_value.bind = bind

        @tasks.task
        def getaddrinfo(*args, **kw):
            return [(2, 1, 6, '', ('0.0.0.1', 80)),
                    (2, 1, 6, '', ('0.0.0.2', 80))]
        self.loop.getaddrinfo = getaddrinfo
        self.loop.sock_connect = unittest.mock.Mock()
        self.loop.sock_connect.side_effect = socket.error('Err2')

        coro = self.loop.create_connection(
            'example.com', 80, family=socket.AF_INET,
            local_addr=(None, 8080))
        with self.assertRaises(socket.error) as cm:
            self.loop.run_until_complete(coro)

        self.assertTrue(str(cm.exception), 'Multiple exceptions: ')
        self.assertTrue(m_socket.socket.return_value.close.called)

    def test_create_connection_no_local_addr(self):
        @tasks.task
        def getaddrinfo(host, *args, **kw):
            if host == 'example.com':
                return [(2, 1, 6, '', ('107.6.106.82', 80)),
                        (2, 1, 6, '', ('107.6.106.82', 80))]
            else:
                return []
        self.loop.getaddrinfo = getaddrinfo

        coro = self.loop.create_connection(
            'example.com', 80, family=socket.AF_INET,
            local_addr=(None, 8080))
        self.assertRaises(
            socket.error, self.loop.run_until_complete, coro)

    def test_start_serving_empty_host(self):
        # if host is empty string use None instead
        host = object()

        @tasks.task
        def getaddrinfo(*args, **kw):
            nonlocal host
            host = args[0]
            yield from []

        self.loop.getaddrinfo = getaddrinfo
        fut = self.loop.start_serving(MyProto, '', 0)
        self.assertRaises(OSError, self.loop.run_until_complete, fut)
        self.assertIsNone(host)

    def test_start_serving_host_port_sock(self):
        fut = self.loop.start_serving(
            MyProto, '0.0.0.0', 0, sock=object())
        self.assertRaises(ValueError, self.loop.run_until_complete, fut)

    def test_start_serving_no_host_port_sock(self):
        fut = self.loop.start_serving(MyProto)
        self.assertRaises(ValueError, self.loop.run_until_complete, fut)

    def test_start_serving_no_getaddrinfo(self):
        getaddrinfo = self.loop.getaddrinfo = unittest.mock.Mock()
        getaddrinfo.return_value = []

        f = self.loop.start_serving(MyProto, '0.0.0.0', 0)
        self.assertRaises(socket.error, self.loop.run_until_complete, f)

    @unittest.mock.patch('tulip.base_events.socket')
    def test_start_serving_cant_bind(self, m_socket):

        class Err(socket.error):
            strerror = 'error'

        m_socket.error = socket.error
        m_socket.getaddrinfo.return_value = [
            (2, 1, 6, '', ('127.0.0.1', 10100))]
        m_sock = m_socket.socket.return_value = unittest.mock.Mock()
        m_sock.bind.side_effect = Err

        fut = self.loop.start_serving(MyProto, '0.0.0.0', 0)
        self.assertRaises(OSError, self.loop.run_until_complete, fut)
        self.assertTrue(m_sock.close.called)

    @unittest.mock.patch('tulip.base_events.socket')
    def test_create_datagram_endpoint_no_addrinfo(self, m_socket):
        m_socket.error = socket.error
        m_socket.getaddrinfo.return_value = []

        coro = self.loop.create_datagram_endpoint(
            local_addr=('localhost', 0))
        self.assertRaises(
            socket.error, self.loop.run_until_complete, coro)

    def test_create_datagram_endpoint_addr_error(self):
        coro = self.loop.create_datagram_endpoint(
            local_addr='localhost')
        self.assertRaises(
            AssertionError, self.loop.run_until_complete, coro)
        coro = self.loop.create_datagram_endpoint(
            local_addr=('localhost', 1, 2, 3))
        self.assertRaises(
            AssertionError, self.loop.run_until_complete, coro)

    def test_create_datagram_endpoint_connect_err(self):
        self.loop.sock_connect = unittest.mock.Mock()
        self.loop.sock_connect.side_effect = socket.error

        coro = self.loop.create_datagram_endpoint(
            remote_addr=('127.0.0.1', 0))
        self.assertRaises(
            socket.error, self.loop.run_until_complete, coro)

    @unittest.mock.patch('tulip.base_events.socket')
    def test_create_datagram_endpoint_socket_err(self, m_socket):
        m_socket.error = socket.error
        m_socket.getaddrinfo = socket.getaddrinfo
        m_socket.socket.side_effect = socket.error

        coro = self.loop.create_datagram_endpoint(
            family=socket.AF_INET)
        self.assertRaises(
            socket.error, self.loop.run_until_complete, coro)

        coro = self.loop.create_datagram_endpoint(
            local_addr=('127.0.0.1', 0))
        self.assertRaises(
            socket.error, self.loop.run_until_complete, coro)

    def test_create_datagram_endpoint_no_matching_family(self):
        coro = self.loop.create_datagram_endpoint(
            remote_addr=('127.0.0.1', 0), local_addr=('::1', 0))
        self.assertRaises(
            ValueError, self.loop.run_until_complete, coro)

    @unittest.mock.patch('tulip.base_events.socket')
    def test_create_datagram_endpoint_setblk_err(self, m_socket):
        m_socket.error = socket.error
        m_socket.socket.return_value.setblocking.side_effect = socket.error

        coro = self.loop.create_datagram_endpoint(
            family=socket.AF_INET)
        self.assertRaises(
            socket.error, self.loop.run_until_complete, coro)
        self.assertTrue(
            m_socket.socket.return_value.close.called)

    def test_create_datagram_endpoint_noaddr_nofamily(self):
        coro = self.loop.create_datagram_endpoint()
        self.assertRaises(ValueError, self.loop.run_until_complete, coro)

    @unittest.mock.patch('tulip.base_events.socket')
    def test_create_datagram_endpoint_cant_bind(self, m_socket):
        class Err(socket.error):
            pass

        m_socket.error = socket.error
        m_socket.AF_INET6 = socket.AF_INET6
        m_socket.getaddrinfo = socket.getaddrinfo
        m_sock = m_socket.socket.return_value = unittest.mock.Mock()
        m_sock.bind.side_effect = Err

        fut = self.loop.create_datagram_endpoint(
            local_addr=('127.0.0.1', 0), family=socket.AF_INET)
        self.assertRaises(Err, self.loop.run_until_complete, fut)
        self.assertTrue(m_sock.close.called)

    def test_accept_connection_retry(self):
        sock = unittest.mock.Mock()
        sock.accept.side_effect = BlockingIOError()

        self.loop._accept_connection(MyProto, sock)
        self.assertFalse(sock.close.called)

    @unittest.mock.patch('tulip.selector_events.tulip_log')
    def test_accept_connection_exception(self, m_log):
        sock = unittest.mock.Mock()
        sock.accept.side_effect = OSError()

        self.loop._accept_connection(MyProto, sock)
        self.assertTrue(sock.close.called)
        self.assertTrue(m_log.exception.called)
