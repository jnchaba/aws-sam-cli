"""
API Gateway Management API emulation for local WebSocket testing
"""
import asyncio
import logging
from threading import Thread

from flask import Flask, jsonify, request

from samcli.local.apigw.websocket_connection_manager import WebSocketConnectionManager

LOG = logging.getLogger(__name__)


class ManagementApiService:
    """
    Emulates API Gateway Management API.

    Provides endpoints for Lambda functions to interact with WebSocket connections:
    - POST /@connections/{connectionId} - Send data to connection
    - DELETE /@connections/{connectionId} - Close connection
    - GET /@connections/{connectionId} - Get connection info
    """

    def __init__(
        self,
        connection_manager: WebSocketConnectionManager,
        port: int = 3001,
        host: str = "127.0.0.1",
    ):
        """
        Initialize Management API service.

        Parameters
        ----------
        connection_manager : WebSocketConnectionManager
            Connection manager
        port : int
            Port to bind to (same as WebSocket port)
        host : str
            Host to bind to
        """
        self.connection_manager = connection_manager
        self.port = port
        self.host = host
        self.app = Flask(__name__)
        self.app.logger.setLevel(logging.ERROR)  # Reduce Flask logging noise
        self._setup_routes()

    def _setup_routes(self):
        """Setup Flask routes for Management API."""

        @self.app.route("/@connections/<connection_id>", methods=["POST"])
        def post_to_connection(connection_id):
            """Send data to WebSocket connection."""
            websocket = self.connection_manager.get_connection(connection_id)

            if not websocket:
                LOG.warning("POST /@connections/%s - Connection not found", connection_id)
                return jsonify({"message": "GoneException", "__type": "GoneException"}), 410

            data = request.get_data()
            LOG.debug("Management API: Sending %d bytes to %s", len(data), connection_id)

            try:
                # Send data via WebSocket (requires asyncio)
                # Create new event loop since we're in a Flask thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(websocket.send(data))
                finally:
                    loop.close()

                return "", 200
            except Exception as e:
                LOG.error("Error sending to connection %s: %s", connection_id, e)
                # If send fails, connection is probably gone
                self.connection_manager.remove_connection(connection_id)
                return jsonify({"message": "GoneException", "__type": "GoneException"}), 410

        @self.app.route("/@connections/<connection_id>", methods=["DELETE"])
        def delete_connection(connection_id):
            """Close WebSocket connection."""
            websocket = self.connection_manager.get_connection(connection_id)

            if not websocket:
                LOG.warning("DELETE /@connections/%s - Connection not found", connection_id)
                return jsonify({"message": "GoneException", "__type": "GoneException"}), 410

            LOG.debug("Management API: Closing connection %s", connection_id)

            try:
                # Close WebSocket connection
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(websocket.close())
                finally:
                    loop.close()

                self.connection_manager.remove_connection(connection_id)
                return "", 204
            except Exception as e:
                LOG.error("Error closing connection %s: %s", connection_id, e)
                self.connection_manager.remove_connection(connection_id)
                return "", 204  # Return success even if close failed

        @self.app.route("/@connections/<connection_id>", methods=["GET"])
        def get_connection(connection_id):
            """Get connection info."""
            websocket = self.connection_manager.get_connection(connection_id)

            if not websocket:
                LOG.warning("GET /@connections/%s - Connection not found", connection_id)
                return jsonify({"message": "GoneException", "__type": "GoneException"}), 410

            # Return basic connection info (mocked for local testing)
            import time

            return (
                jsonify(
                    {
                        "connectedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "identity": {
                            "sourceIp": "127.0.0.1",
                        },
                        "lastActiveAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                ),
                200,
            )

    def start(self):
        """Start Management API server (blocking)."""
        LOG.info("Starting Management API on http://%s:%d/@connections/{{connectionId}}", self.host, self.port)

        # Run Flask with minimal logging
        self.app.run(host=self.host, port=self.port, threaded=True, use_reloader=False)

    def start_in_thread(self) -> Thread:
        """
        Start Management API server in background thread.

        Returns
        -------
        Thread
            Server thread
        """
        thread = Thread(target=self.start, daemon=True, name="ManagementApiService")
        thread.start()
        LOG.debug("Started Management API service thread")
        return thread
