"""
Local WebSocket API Gateway service for SAM CLI
"""
import asyncio
import json
import logging
from threading import Thread
from typing import Dict, List, Optional

import websockets
from websockets.server import WebSocketServerProtocol

from samcli.local.apigw.route import Route
from samcli.local.apigw.websocket_connection_manager import WebSocketConnectionManager
from samcli.local.apigw.websocket_event_constructor import (
    construct_websocket_event,
    get_event_type_from_route_key,
)

LOG = logging.getLogger(__name__)


class LocalWebSocketService:
    """
    Local WebSocket API Gateway service.

    Emulates API Gateway WebSocket APIs by:
    - Accepting WebSocket connections
    - Routing messages to Lambda functions
    - Managing connection lifecycle
    """

    def __init__(
        self,
        routes: List[Route],
        lambda_runner,
        connection_manager: WebSocketConnectionManager,
        port: int = 3001,
        host: str = "127.0.0.1",
        route_selection_expression: str = "$request.body.action",
    ):
        """
        Initialize WebSocket service.

        Parameters
        ----------
        routes : list of Route
            WebSocket routes
        lambda_runner
            Lambda invocation runner
        connection_manager : WebSocketConnectionManager
            Connection manager
        port : int
            Port to bind to
        host : str
            Host to bind to
        route_selection_expression : str
            Expression to extract route from message
        """
        self.routes = self._build_route_map(routes)
        self.lambda_runner = lambda_runner
        self.connection_manager = connection_manager
        self.port = port
        self.host = host
        self.route_selection_expression = route_selection_expression
        self.server = None

    def _build_route_map(self, routes: List[Route]) -> Dict[str, Route]:
        """
        Build map of route_key -> Route.

        Parameters
        ----------
        routes : list of Route
            WebSocket routes

        Returns
        -------
        dict
            Mapping of route key to Route object
        """
        route_map = {}
        for route in routes:
            if route.is_websocket():
                route_map[route.route_key] = route
                LOG.debug("Registered WebSocket route: %s -> %s", route.route_key, route.function_name)
        return route_map

    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """
        Handle a WebSocket connection.

        Parameters
        ----------
        websocket : WebSocketServerProtocol
            WebSocket connection
        path : str
            Connection path
        """
        connection_id = self.connection_manager.register_connection(websocket)
        LOG.info("WebSocket connection established: %s", connection_id)

        try:
            # Invoke $connect route
            connect_success = await self._invoke_route(
                Route.WEBSOCKET_CONNECT, connection_id, None, websocket
            )

            if not connect_success:
                LOG.warning("$connect route rejected connection: %s", connection_id)
                await websocket.close(1008, "Connection rejected")
                return

            # Handle messages
            async for message in websocket:
                await self._handle_message(connection_id, message, websocket)

        except websockets.exceptions.ConnectionClosed as e:
            LOG.debug("WebSocket connection closed: %s (code=%s, reason=%s)", connection_id, e.code, e.reason)
        except Exception as e:
            LOG.error("Error in WebSocket connection %s: %s", connection_id, e, exc_info=True)
        finally:
            # Invoke $disconnect route
            await self._invoke_route(Route.WEBSOCKET_DISCONNECT, connection_id, None, websocket)
            self.connection_manager.remove_connection(connection_id)
            LOG.info("WebSocket connection terminated: %s", connection_id)

    async def _handle_message(self, connection_id: str, message: str, websocket: WebSocketServerProtocol):
        """
        Handle incoming WebSocket message.

        Parameters
        ----------
        connection_id : str
            Connection ID
        message : str
            Message payload
        websocket : WebSocketServerProtocol
            WebSocket connection
        """
        LOG.debug("Received message from %s: %s", connection_id, message[:100] if len(message) > 100 else message)

        # Determine route from message
        route_key = self._extract_route_key(message)
        LOG.debug("Matched route: %s", route_key)

        # Invoke Lambda
        await self._invoke_route(route_key, connection_id, message, websocket)

    def _extract_route_key(self, message: str) -> str:
        """
        Extract route key from message using route selection expression.

        Parameters
        ----------
        message : str
            Message payload

        Returns
        -------
        str
            Route key
        """
        # Parse route selection expression
        # For now, support $request.body.action
        if "$request.body.action" in self.route_selection_expression:
            try:
                body = json.loads(message)
                action = body.get("action")
                if action and action in self.routes:
                    return action
            except (json.JSONDecodeError, AttributeError):
                LOG.debug("Could not parse message as JSON: %s", message[:100])

        # Fall back to $default
        return Route.WEBSOCKET_DEFAULT

    async def _invoke_route(
        self,
        route_key: str,
        connection_id: str,
        body: Optional[str],
        websocket: WebSocketServerProtocol,
    ) -> bool:
        """
        Invoke Lambda function for route.

        Parameters
        ----------
        route_key : str
            Route key
        connection_id : str
            Connection ID
        body : str, optional
            Message body
        websocket : WebSocketServerProtocol
            WebSocket connection

        Returns
        -------
        bool
            True if invocation succeeded, False otherwise
        """
        route = self.routes.get(route_key)
        if not route:
            LOG.warning("No route found for %s", route_key)
            # For non-existent routes, just return success
            return True

        # Build WebSocket event
        event_type = get_event_type_from_route_key(route_key)
        event = construct_websocket_event(
            connection_id=connection_id,
            route_key=route_key,
            body=body,
            event_type=event_type,
        )

        # Invoke Lambda in thread pool to avoid blocking asyncio
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None,
                self._invoke_lambda_sync,
                route.function_name,
                event,
            )

            # Handle Lambda response
            if response:
                success = await self._handle_lambda_response(response, route_key, websocket)
                return success
            else:
                # No response or error - for $connect, reject; for others, continue
                return route_key != Route.WEBSOCKET_CONNECT

        except Exception as e:
            LOG.error("Error invoking Lambda for route %s: %s", route_key, e, exc_info=True)
            return route_key != Route.WEBSOCKET_CONNECT

    def _invoke_lambda_sync(self, function_name: str, event: dict) -> Optional[str]:
        """
        Invoke Lambda function synchronously.

        Parameters
        ----------
        function_name : str
            Function name
        event : dict
            Event payload

        Returns
        -------
        str or None
            Lambda response
        """
        try:
            LOG.info("Invoking %s", function_name)
            response, _, _ = self.lambda_runner.invoke(
                function_name=function_name,
                event=json.dumps(event),
                stdout=None,
                stderr=None,
            )
            return response.decode("utf-8") if response else None
        except Exception as e:
            LOG.error("Lambda invocation error for %s: %s", function_name, e)
            return None

    async def _handle_lambda_response(
        self, response: str, route_key: str, websocket: WebSocketServerProtocol
    ) -> bool:
        """
        Handle Lambda response and send to client.

        Parameters
        ----------
        response : str
            Lambda response
        route_key : str
            Route key that was invoked
        websocket : WebSocketServerProtocol
            WebSocket connection

        Returns
        -------
        bool
            True if response indicates success, False for failure
        """
        try:
            response_json = json.loads(response)
            status_code = response_json.get("statusCode", 200)

            # For $connect, non-2xx status code means reject connection
            if route_key == Route.WEBSOCKET_CONNECT:
                return 200 <= status_code < 300

            # For MESSAGE routes, send response body to client if present
            if status_code == 200 and route_key not in [Route.WEBSOCKET_CONNECT, Route.WEBSOCKET_DISCONNECT]:
                body = response_json.get("body")
                if body:
                    await websocket.send(body)

            return True

        except (json.JSONDecodeError, AttributeError) as e:
            LOG.error("Error parsing Lambda response: %s", e)
            return route_key != Route.WEBSOCKET_CONNECT

    def start(self):
        """Start WebSocket server (blocking)."""
        LOG.info("Starting WebSocket server on ws://%s:%d", self.host, self.port)

        async def serve():
            async with websockets.serve(self.handle_connection, self.host, self.port):
                await asyncio.Future()  # Run forever

        try:
            asyncio.run(serve())
        except KeyboardInterrupt:
            LOG.info("WebSocket server interrupted")
        except Exception as e:
            LOG.error("WebSocket server error: %s", e, exc_info=True)

    def start_in_thread(self) -> Thread:
        """
        Start WebSocket server in background thread.

        Returns
        -------
        Thread
            Server thread
        """
        thread = Thread(target=self.start, daemon=True, name="WebSocketService")
        thread.start()
        LOG.debug("Started WebSocket service thread")
        return thread
