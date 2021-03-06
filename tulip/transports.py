"""Abstract Transport class."""

__all__ = ['ReadTransport', 'WriteTransport', 'Transport']


class BaseTransport:
    """Base ABC for transports."""

    def __init__(self, extra=None):
        if extra is None:
            extra = {}
        self._extra = extra

    def get_extra_info(self, name, default=None):
        """Get optional transport information."""
        return self._extra.get(name, default)

    def register_protocol(self, protocol):
        """Registers a Protocol to receive events regarding this transport."""
        raise NotImplementedError

    def close(self):
        """Closes the transport.

        Buffered data will be flushed asynchronously.  No more data
        will be received.  After all buffered data is flushed, the
        protocol's connection_lost() method will (eventually) called
        with None as its argument.
        """
        raise NotImplementedError


class ReadTransport(BaseTransport):
    """ABC for read-only transports."""

    def pause(self):
        """Pause the receiving end.

        No data will be passed to the protocol's data_received()
        method until resume() is called.
        """
        raise NotImplementedError

    def resume(self):
        """Resume the receiving end.

        Data received will once again be passed to the protocol's
        data_received() method.
        """
        raise NotImplementedError


class WriteTransport(BaseTransport):
    """ABC for write-only transports."""

    def write(self, data):
        """Write some data bytes to the transport.

        This does not block; it buffers the data and arranges for it
        to be sent out asynchronously.
        """
        raise NotImplementedError

    def writelines(self, list_of_data):
        """Write a list (or any iterable) of data bytes to the transport.

        The default implementation just calls write() for each item in
        the list/iterable.
        """
        for data in list_of_data:
            self.write(data)

    def write_eof(self):
        """Closes the write end after flushing buffered data.

        (This is like typing ^D into a UNIX program reading from stdin.)

        Data may still be received.
        """
        raise NotImplementedError

    def can_write_eof(self):
        """Return True if this protocol supports write_eof(), False if not."""
        raise NotImplementedError

    def pause_writing(self):
        """Pause transmission on the transport.

        Subsequent writes are deferred until resume_writing() is called.
        """
        raise NotImplementedError

    def resume_writing(self):
        """Resume transmission on the transport. """
        raise NotImplementedError

    def discard_output(self):
        """Discard any buffered data awaiting transmission on the transport."""
        raise NotImplementedError

    def abort(self):
        """Closes the transport immediately.

        Buffered data will be lost.  No more data will be received.
        The protocol's connection_lost() method will (eventually) be
        called with None as its argument.
        """
        raise NotImplementedError


class Transport(ReadTransport, WriteTransport):
    """ABC representing a bidirectional transport.

    There may be several implementations, but typically, the user does
    not implement new transports; rather, the platform provides some
    useful transports that are implemented using the platform's best
    practices.

    The user never instantiates a transport directly; they call a
    utility function, passing it information necessary to create the
    transport and protocol.  (E.g.  EventLoop.create_connection() or
    EventLoop.start_serving().)

    The utility function will asynchronously create a transport and
    pass it back to user code, where callbacks may be registered.

    The implementation here raises NotImplemented for every method
    except writelines(), which calls write() in a loop.
    """


class DatagramTransport(BaseTransport):
    """ABC for datagram (UDP) transports."""

    def sendto(self, data, addr=None):
        """Send data to the transport.

        This does not block; it buffers the data and arranges for it
        to be sent out asynchronously.
        addr is target socket address.
        If addr is None use target address pointed on transport creation.
        """
        raise NotImplementedError

    def abort(self):
        """Closes the transport immediately.

        Buffered data will be lost.  No more data will be received.
        The protocol's connection_lost() method will (eventually) be
        called with None as its argument.
        """
        raise NotImplementedError
