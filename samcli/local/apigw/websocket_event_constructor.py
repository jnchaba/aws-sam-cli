"""
WebSocket event construction for API Gateway WebSocket APIs
"""
import time
import uuid
from typing import Any, Dict, Optional


def construct_websocket_event(
    connection_id: str,
    route_key: str,
    body: Optional[str] = None,
    event_type: str = "MESSAGE",
    domain_name: str = "localhost",
    stage: str = "$default",
) -> Dict[str, Any]:
    """
    Construct an API Gateway WebSocket event.

    Parameters
    ----------
    connection_id : str
        Unique connection identifier
    route_key : str
        WebSocket route key ($connect, $disconnect, $default, or custom)
    body : str, optional
        Message body (for MESSAGE events)
    event_type : str
        Event type: CONNECT, MESSAGE, or DISCONNECT
    domain_name : str
        Domain name (default: localhost)
    stage : str
        Stage name (default: $default)

    Returns
    -------
    dict
        WebSocket event in API Gateway format

    Examples
    --------
    Connect event:

    >>> construct_websocket_event(
    ...     connection_id="abc123",
    ...     route_key="$connect",
    ...     event_type="CONNECT"
    ... )
    {'requestContext': {'routeKey': '$connect', ...}, ...}

    Message event:

    >>> construct_websocket_event(
    ...     connection_id="abc123",
    ...     route_key="sendMessage",
    ...     body='{"action":"sendMessage","data":"Hello"}',
    ...     event_type="MESSAGE"
    ... )
    {'requestContext': {'routeKey': 'sendMessage', ...}, 'body': '{"action":"sendMessage","data":"Hello"}', ...}
    """
    request_time_epoch = int(time.time() * 1000)
    request_time = time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime())
    request_id = str(uuid.uuid4())

    event = {
        "requestContext": {
            "routeKey": route_key,
            "eventType": event_type,
            "connectionId": connection_id,
            "apiId": "local-api-id",
            "domainName": domain_name,
            "stage": stage,
            "requestId": request_id,
            "requestTime": request_time,
            "requestTimeEpoch": request_time_epoch,
        },
        "isBase64Encoded": False,
    }

    # Add body for MESSAGE events
    if body is not None and event_type == "MESSAGE":
        event["body"] = body

    return event


def get_event_type_from_route_key(route_key: str) -> str:
    """
    Determine event type from route key.

    Parameters
    ----------
    route_key : str
        WebSocket route key

    Returns
    -------
    str
        Event type: CONNECT, DISCONNECT, or MESSAGE
    """
    if route_key == "$connect":
        return "CONNECT"
    elif route_key == "$disconnect":
        return "DISCONNECT"
    else:
        return "MESSAGE"
