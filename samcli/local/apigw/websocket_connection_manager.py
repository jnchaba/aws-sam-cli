"""
WebSocket connection management for local API Gateway emulation
"""
import logging
import uuid
from threading import Lock
from typing import Dict, List, Optional

LOG = logging.getLogger(__name__)


class WebSocketConnectionManager:
    """
    Thread-safe manager for WebSocket connections.

    Manages active WebSocket connections with unique connection IDs,
    enabling lookup for Management API operations.
    """

    def __init__(self):
        """Initialize connection manager with empty registry."""
        self._connections: Dict[str, any] = {}
        self._lock = Lock()

    def register_connection(self, websocket) -> str:
        """
        Register a new WebSocket connection.

        Parameters
        ----------
        websocket
            WebSocket connection object

        Returns
        -------
        str
            Unique connection ID (UUID4 format)
        """
        connection_id = str(uuid.uuid4())

        with self._lock:
            self._connections[connection_id] = websocket

        LOG.debug("Registered connection: %s", connection_id)
        return connection_id

    def get_connection(self, connection_id: str) -> Optional[any]:
        """
        Retrieve a WebSocket connection by ID.

        Parameters
        ----------
        connection_id : str
            Connection ID to lookup

        Returns
        -------
        WebSocket or None
            WebSocket connection if found, None otherwise
        """
        with self._lock:
            return self._connections.get(connection_id)

    def remove_connection(self, connection_id: str) -> bool:
        """
        Remove a connection from the registry.

        Parameters
        ----------
        connection_id : str
            Connection ID to remove

        Returns
        -------
        bool
            True if connection was removed, False if not found
        """
        with self._lock:
            if connection_id in self._connections:
                del self._connections[connection_id]
                LOG.debug("Removed connection: %s", connection_id)
                return True
            return False

    def list_connections(self) -> List[str]:
        """
        Get list of all active connection IDs.

        Returns
        -------
        list of str
            List of connection IDs
        """
        with self._lock:
            return list(self._connections.keys())

    def count(self) -> int:
        """
        Get number of active connections.

        Returns
        -------
        int
            Number of connections
        """
        with self._lock:
            return len(self._connections)
