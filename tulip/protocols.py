"""Abstract Protocol class."""

__all__ = ['Protocol', 'DatagramProtocol']


class BaseProtocol:
    """ABC for base protocol class.

    Usually user implements protocols that derived from BaseProtocol
    like Protocol or ProcessProtocol.

    The only case when BaseProtocol should be implemented directly is
    write-only transport like write pipe
    """

    def connection_lost(self, exc):
        """Called when the connection is lost or closed.

        The argument is an exception object or None (the latter
        meaning a regular EOF is received or the connection was
        aborted or closed).
        """


class Protocol(BaseProtocol):
    """ABC representing a protocol.

    The user should implement this interface.  They can inherit from
    this class but don't need to.  The implementations here do
    nothing (they don't raise exceptions).

    After a connection is made (e.g., by
    EventLoop.create_connection()), protocols can be registered with a
    transport to receive its callbacks.

    Once registered, data_received() will be called 0 or more times
    with data (bytes) received from the transport; finally,
    connection_lost() will be called exactly once with either an
    exception object or None as an argument.

    State machine of calls:

      start -> registered [-> DR*] [-> ER?] -> CL -> end
    """

    def data_received(self, data):
        """Called when some data is received.

        The argument is a bytes object.
        """

    def eof_received(self):
        """Called when the other end calls write_eof() or equivalent.

        The default implementation does nothing.

        TODO: By default close the transport.  But we don't have the
        transport as an instance variable (connection_made() may not
        set it).
        """


class DatagramProtocol(BaseProtocol):
    """ABC representing a datagram protocol."""

    def datagram_received(self, data, addr):
        """Called when some datagram is received."""

    def connection_refused(self, exc):
        """Connection is refused."""
