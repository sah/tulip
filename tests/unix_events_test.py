"""Tests for unix_events.py."""

import errno
import io
import unittest
import unittest.mock

try:
    import signal
except ImportError:
    signal = None

from tulip import events
from tulip import futures
from tulip import protocols
from tulip import unix_events
from tulip import transports


@unittest.skipUnless(signal, 'Signals are not supported')
class SelectorEventLoopTests(unittest.TestCase):

    def setUp(self):
        self.loop = unix_events.SelectorEventLoop()
        events.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_check_signal(self):
        self.assertRaises(
            TypeError, self.loop._check_signal, '1')
        self.assertRaises(
            ValueError, self.loop._check_signal, signal.NSIG + 1)

        unix_events.signal = None

        def restore_signal():
            unix_events.signal = signal
        self.addCleanup(restore_signal)

        self.assertRaises(
            RuntimeError, self.loop._check_signal, signal.SIGINT)

    def test_handle_signal_no_handler(self):
        self.loop._handle_signal(signal.NSIG + 1, ())

    def test_handle_signal_cancelled_handler(self):
        h = events.Handle(unittest.mock.Mock(), ())
        h.cancel()
        self.loop._signal_handlers[signal.NSIG + 1] = h
        self.loop.remove_signal_handler = unittest.mock.Mock()
        self.loop._handle_signal(signal.NSIG + 1, ())
        self.loop.remove_signal_handler.assert_called_with(signal.NSIG + 1)

    @unittest.mock.patch('tulip.unix_events.signal')
    def test_add_signal_handler_setup_error(self, m_signal):
        m_signal.NSIG = signal.NSIG
        m_signal.set_wakeup_fd.side_effect = ValueError

        self.assertRaises(
            RuntimeError,
            self.loop.add_signal_handler,
            signal.SIGINT, lambda: True)

    @unittest.mock.patch('tulip.unix_events.signal')
    def test_add_signal_handler(self, m_signal):
        m_signal.NSIG = signal.NSIG

        cb = lambda: True
        self.loop.add_signal_handler(signal.SIGHUP, cb)
        h = self.loop._signal_handlers.get(signal.SIGHUP)
        self.assertTrue(isinstance(h, events.Handle))
        self.assertEqual(h._callback, cb)

    @unittest.mock.patch('tulip.unix_events.signal')
    def test_add_signal_handler_install_error(self, m_signal):
        m_signal.NSIG = signal.NSIG

        def set_wakeup_fd(fd):
            if fd == -1:
                raise ValueError()
        m_signal.set_wakeup_fd = set_wakeup_fd

        class Err(OSError):
            errno = errno.EFAULT
        m_signal.signal.side_effect = Err

        self.assertRaises(
            Err,
            self.loop.add_signal_handler,
            signal.SIGINT, lambda: True)

    @unittest.mock.patch('tulip.unix_events.signal')
    @unittest.mock.patch('tulip.unix_events.tulip_log')
    def test_add_signal_handler_install_error2(self, m_logging, m_signal):
        m_signal.NSIG = signal.NSIG

        class Err(OSError):
            errno = errno.EINVAL
        m_signal.signal.side_effect = Err

        self.loop._signal_handlers[signal.SIGHUP] = lambda: True
        self.assertRaises(
            RuntimeError,
            self.loop.add_signal_handler,
            signal.SIGINT, lambda: True)
        self.assertFalse(m_logging.info.called)
        self.assertEqual(1, m_signal.set_wakeup_fd.call_count)

    @unittest.mock.patch('tulip.unix_events.signal')
    @unittest.mock.patch('tulip.unix_events.tulip_log')
    def test_add_signal_handler_install_error3(self, m_logging, m_signal):
        class Err(OSError):
            errno = errno.EINVAL
        m_signal.signal.side_effect = Err
        m_signal.NSIG = signal.NSIG

        self.assertRaises(
            RuntimeError,
            self.loop.add_signal_handler,
            signal.SIGINT, lambda: True)
        self.assertFalse(m_logging.info.called)
        self.assertEqual(2, m_signal.set_wakeup_fd.call_count)

    @unittest.mock.patch('tulip.unix_events.signal')
    def test_remove_signal_handler(self, m_signal):
        m_signal.NSIG = signal.NSIG

        self.loop.add_signal_handler(signal.SIGHUP, lambda: True)

        self.assertTrue(
            self.loop.remove_signal_handler(signal.SIGHUP))
        self.assertTrue(m_signal.set_wakeup_fd.called)
        self.assertTrue(m_signal.signal.called)
        self.assertEqual(
            (signal.SIGHUP, m_signal.SIG_DFL), m_signal.signal.call_args[0])

    @unittest.mock.patch('tulip.unix_events.signal')
    def test_remove_signal_handler_2(self, m_signal):
        m_signal.NSIG = signal.NSIG
        m_signal.SIGINT = signal.SIGINT

        self.loop.add_signal_handler(signal.SIGINT, lambda: True)
        self.loop._signal_handlers[signal.SIGHUP] = object()
        m_signal.set_wakeup_fd.reset_mock()

        self.assertTrue(
            self.loop.remove_signal_handler(signal.SIGINT))
        self.assertFalse(m_signal.set_wakeup_fd.called)
        self.assertTrue(m_signal.signal.called)
        self.assertEqual(
            (signal.SIGINT, m_signal.default_int_handler),
            m_signal.signal.call_args[0])

    @unittest.mock.patch('tulip.unix_events.signal')
    @unittest.mock.patch('tulip.unix_events.tulip_log')
    def test_remove_signal_handler_cleanup_error(self, m_logging, m_signal):
        m_signal.NSIG = signal.NSIG
        self.loop.add_signal_handler(signal.SIGHUP, lambda: True)

        m_signal.set_wakeup_fd.side_effect = ValueError

        self.loop.remove_signal_handler(signal.SIGHUP)
        self.assertTrue(m_logging.info)

    @unittest.mock.patch('tulip.unix_events.signal')
    def test_remove_signal_handler_error(self, m_signal):
        m_signal.NSIG = signal.NSIG
        self.loop.add_signal_handler(signal.SIGHUP, lambda: True)

        m_signal.signal.side_effect = OSError

        self.assertRaises(
            OSError, self.loop.remove_signal_handler, signal.SIGHUP)

    @unittest.mock.patch('tulip.unix_events.signal')
    def test_remove_signal_handler_error2(self, m_signal):
        m_signal.NSIG = signal.NSIG
        self.loop.add_signal_handler(signal.SIGHUP, lambda: True)

        class Err(OSError):
            errno = errno.EINVAL
        m_signal.signal.side_effect = Err

        self.assertRaises(
            RuntimeError, self.loop.remove_signal_handler, signal.SIGHUP)


class UnixReadPipeTransportTests(unittest.TestCase):

    def setUp(self):
        self.loop = unittest.mock.Mock(spec_set=events.AbstractEventLoop)
        self.pipe = unittest.mock.Mock(spec_set=io.RawIOBase)
        self.pipe.fileno.return_value = 5
        self.protocol = unittest.mock.Mock(spec_set=protocols.Protocol)

    @unittest.mock.patch('fcntl.fcntl')
    def test_ctor(self, m_fcntl):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)
        self.assertEqual(self.loop.call_soon.call_count, 0)

    @unittest.mock.patch('fcntl.fcntl')
    def test_ctor_with_waiter(self, m_fcntl):
        fut = futures.Future()
        unix_events._UnixReadPipeTransport(
            self.loop, self.pipe, fut)
        self.loop.call_soon.assert_called_with(fut.set_result, None)
        fut.cancel()

    @unittest.mock.patch('fcntl.fcntl')
    def test_register_protocol(self, m_fcntl):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)
        self.loop.add_reader.assert_called_with(5, tr._read_ready)

    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test__read_ready(self, m_fcntl, m_read):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)
        m_read.return_value = b'data'
        tr._read_ready()

        m_read.assert_called_with(5, tr.max_size)
        self.protocol.data_received.assert_called_with(b'data')

    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test__read_ready_eof(self, m_fcntl, m_read):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)
        m_read.return_value = b''
        tr._read_ready()

        m_read.assert_called_with(5, tr.max_size)
        self.loop.remove_reader.assert_called_with(5)
        self.protocol.eof_received.assert_called_with()

    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test__read_ready_blocked(self, m_fcntl, m_read):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)
        self.loop.reset_mock()
        m_read.side_effect = BlockingIOError
        tr._read_ready()

        m_read.assert_called_with(5, tr.max_size)
        self.assertFalse(self.protocol.data_received.called)

    @unittest.mock.patch('tulip.log.tulip_log.exception')
    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test__read_ready_error(self, m_fcntl, m_read, m_logexc):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)
        err = OSError()
        m_read.side_effect = err
        tr._close = unittest.mock.Mock()
        tr._read_ready()

        m_read.assert_called_with(5, tr.max_size)
        tr._close.assert_called_with(err)
        m_logexc.assert_called_with('Fatal error for %s', tr)

    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test_pause(self, m_fcntl, m_read):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)

        tr.pause()
        self.loop.remove_reader.assert_called_with(5)

    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test_resume(self, m_fcntl, m_read):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)

        tr.resume()
        self.loop.add_reader.assert_called_with(5, tr._read_ready)

    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test_close(self, m_fcntl, m_read):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)

        tr._close = unittest.mock.Mock()
        tr.close()
        tr._close.assert_called_with(None)

    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test_close_already_closing(self, m_fcntl, m_read):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)

        tr._closing = True
        tr._close = unittest.mock.Mock()
        tr.close()
        self.assertFalse(tr._close.called)

    @unittest.mock.patch('os.read')
    @unittest.mock.patch('fcntl.fcntl')
    def test__close(self, m_fcntl, m_read):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)

        err = object()
        tr._close(err)
        self.assertTrue(tr._closing)
        self.loop.remove_reader.assert_called_with(5)
        self.loop.call_soon.assert_called_with(tr._call_connection_lost, err)

    @unittest.mock.patch('fcntl.fcntl')
    def test__call_connection_lost(self, m_fcntl):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)

        err = None
        tr._call_connection_lost(err)
        self.protocol.connection_lost.assert_called_with(err)
        self.pipe.close.assert_called_with()

    @unittest.mock.patch('fcntl.fcntl')
    def test__call_connection_lost_with_err(self, m_fcntl):
        tr = unix_events._UnixReadPipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)

        err = OSError()
        tr._call_connection_lost(err)
        self.protocol.connection_lost.assert_called_with(err)
        self.pipe.close.assert_called_with()


class UnixWritePipeTransportTests(unittest.TestCase):

    def setUp(self):
        self.loop = unittest.mock.Mock(spec_set=events.AbstractEventLoop)
        self.pipe = unittest.mock.Mock(spec_set=io.RawIOBase)
        self.pipe.fileno.return_value = 5
        self.protocol = unittest.mock.Mock(spec_set=protocols.Protocol)

    @unittest.mock.patch('fcntl.fcntl')
    def test_ctor(self, m_fcntl):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

    @unittest.mock.patch('fcntl.fcntl')
    def test_ctor_with_waiter(self, m_fcntl):
        fut = futures.Future()
        unix_events._UnixWritePipeTransport(
            self.loop, self.pipe, fut)
        self.loop.call_soon.assert_called_with(fut.set_result, None)
        fut.cancel()

    @unittest.mock.patch('fcntl.fcntl')
    def test_can_write_eof(self, m_fcntl):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)
        self.assertTrue(tr.can_write_eof())

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test_write(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        m_write.return_value = 4
        tr.write(b'data')
        m_write.assert_called_with(5, b'data')
        self.assertFalse(self.loop.add_writer.called)
        self.assertEqual([], tr._buffer)

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test_write_no_data(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr.write(b'')
        self.assertFalse(m_write.called)
        self.assertFalse(self.loop.add_writer.called)
        self.assertEqual([], tr._buffer)

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test_write_partial(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        m_write.return_value = 2
        tr.write(b'data')
        m_write.assert_called_with(5, b'data')
        self.loop.add_writer.assert_called_with(5, tr._write_ready)
        self.assertEqual([b'ta'], tr._buffer)

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test_write_buffer(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr._buffer = [b'previous']
        tr.write(b'data')
        self.assertFalse(m_write.called)
        self.assertFalse(self.loop.add_writer.called)
        self.assertEqual([b'previous', b'data'], tr._buffer)

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test_write_again(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        m_write.side_effect = BlockingIOError()
        tr.write(b'data')
        m_write.assert_called_with(5, b'data')
        self.loop.add_writer.assert_called_with(5, tr._write_ready)
        self.assertEqual([b'data'], tr._buffer)

    @unittest.mock.patch('tulip.unix_events.tulip_log')
    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test_write_err(self, m_fcntl, m_write, m_log):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        err = OSError()
        m_write.side_effect = err
        tr._fatal_error = unittest.mock.Mock()
        tr.write(b'data')
        m_write.assert_called_with(5, b'data')
        self.assertFalse(self.loop.called)
        self.assertEqual([], tr._buffer)
        tr._fatal_error.assert_called_with(err)
        self.assertEqual(1, tr._conn_lost)

        tr.write(b'data')
        self.assertEqual(2, tr._conn_lost)
        tr.write(b'data')
        tr.write(b'data')
        tr.write(b'data')
        tr.write(b'data')
        m_log.warning.assert_called_with(
            'os.write(pipe, data) raised exception.')

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test__write_ready(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)
        tr._buffer = [b'da', b'ta']
        m_write.return_value = 4
        tr._write_ready()
        m_write.assert_called_with(5, b'data')
        self.loop.remove_writer.assert_called_with(5)
        self.assertEqual([], tr._buffer)

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test__write_ready_partial(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr._buffer = [b'da', b'ta']
        m_write.return_value = 3
        tr._write_ready()
        m_write.assert_called_with(5, b'data')
        self.assertFalse(self.loop.remove_writer.called)
        self.assertEqual([b'a'], tr._buffer)

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test__write_ready_again(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr._buffer = [b'da', b'ta']
        m_write.side_effect = BlockingIOError()
        tr._write_ready()
        m_write.assert_called_with(5, b'data')
        self.assertFalse(self.loop.remove_writer.called)
        self.assertEqual([b'data'], tr._buffer)

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test__write_ready_empty(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr._buffer = [b'da', b'ta']
        m_write.return_value = 0
        tr._write_ready()
        m_write.assert_called_with(5, b'data')
        self.assertFalse(self.loop.remove_writer.called)
        self.assertEqual([b'data'], tr._buffer)

    @unittest.mock.patch('tulip.log.tulip_log.exception')
    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test__write_ready_err(self, m_fcntl, m_write, m_logexc):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr._buffer = [b'da', b'ta']
        m_write.side_effect = err = OSError()
        tr._write_ready()
        m_write.assert_called_with(5, b'data')
        self.loop.remove_writer.assert_called_with(5)
        self.assertEqual([], tr._buffer)
        self.assertTrue(tr._closing)
        self.loop.call_soon.assert_called_with(
            tr._call_connection_lost, err)
        m_logexc.assert_called_with('Fatal error for %s', tr)
        self.assertEqual(1, tr._conn_lost)

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test__write_ready_closing(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)

        tr._closing = True
        tr._buffer = [b'da', b'ta']
        m_write.return_value = 4
        tr._write_ready()
        m_write.assert_called_with(5, b'data')
        self.loop.remove_writer.assert_called_with(5)
        self.assertEqual([], tr._buffer)
        self.protocol.connection_lost.assert_called_with(None)
        self.pipe.close.assert_called_with()

    @unittest.mock.patch('os.write')
    @unittest.mock.patch('fcntl.fcntl')
    def test_abort(self, m_fcntl, m_write):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr._buffer = [b'da', b'ta']
        tr.abort()
        self.assertFalse(m_write.called)
        self.loop.remove_writer.assert_called_with(5)
        self.assertEqual([], tr._buffer)
        self.assertTrue(tr._closing)
        self.loop.call_soon.assert_called_with(
            tr._call_connection_lost, None)

    @unittest.mock.patch('fcntl.fcntl')
    def test__call_connection_lost(self, m_fcntl):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)

        err = None
        tr._call_connection_lost(err)
        self.protocol.connection_lost.assert_called_with(err)
        self.pipe.close.assert_called_with()

    @unittest.mock.patch('fcntl.fcntl')
    def test__call_connection_lost_with_err(self, m_fcntl):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)

        err = OSError()
        tr._call_connection_lost(err)
        self.protocol.connection_lost.assert_called_with(err)
        self.pipe.close.assert_called_with()

    @unittest.mock.patch('fcntl.fcntl')
    def test_close(self, m_fcntl):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr.write_eof = unittest.mock.Mock()
        tr.close()
        tr.write_eof.assert_called_with()

    @unittest.mock.patch('fcntl.fcntl')
    def test_close_closing(self, m_fcntl):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr.write_eof = unittest.mock.Mock()
        tr._closing = True
        tr.close()
        self.assertFalse(tr.write_eof.called)

    @unittest.mock.patch('fcntl.fcntl')
    def test_write_eof(self, m_fcntl):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)

        tr.write_eof()
        self.assertTrue(tr._closing)
        self.loop.call_soon.assert_called_with(
            tr._call_connection_lost, None)

    @unittest.mock.patch('fcntl.fcntl')
    def test_write_eof_pending(self, m_fcntl):
        tr = unix_events._UnixWritePipeTransport(self.loop, self.pipe)
        tr.register_protocol(self.protocol)
        tr._buffer = [b'data']
        tr.write_eof()
        self.assertTrue(tr._closing)
        self.assertFalse(self.protocol.connection_lost.called)
