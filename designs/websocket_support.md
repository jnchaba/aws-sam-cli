WebSocket API Support for sam local start-api
==============================================

What is the problem?
--------------------

AWS SAM CLI currently supports local testing of REST APIs and HTTP APIs via `sam local start-api`, but does not support WebSocket APIs (AWS::ApiGatewayV2::Api with `ProtocolType: WEBSOCKET`). This forces developers to deploy to AWS to test WebSocket functionality, significantly slowing down the development cycle.

**Current Pain Points:**
- No local testing for WebSocket Lambda functions
- Cannot test bidirectional communication flows locally
- Must deploy to AWS cloud for every WebSocket change
- Difficult to debug WebSocket connection lifecycle ($connect, $disconnect)
- No way to test Management API (`/@connections/{connectionId}`) locally

**Community Impact:**
- 180+ developers have requested this feature (GitHub issue #2232)
- WebSocket APIs are increasingly common for real-time applications (chat, gaming, live dashboards)
- Competitors (LocalStack) offer WebSocket support

What will be changed?
---------------------

`sam local start-api` will detect WebSocket APIs in SAM/CloudFormation templates and automatically start a WebSocket server alongside the existing HTTP server. The implementation will:

1. Parse `AWS::ApiGatewayV2::Api` resources with `ProtocolType: WEBSOCKET`
2. Start a WebSocket server (using Python `websockets` library) on the same or different port
3. Route WebSocket messages to Lambda functions based on route selection expressions
4. Emulate API Gateway WebSocket event format for Lambda invocations
5. Provide local Management API endpoint for `PostToConnection` operations
6. Manage connection lifecycle ($connect, $disconnect, custom routes)

**Compatibility:**
- Existing REST API and HTTP API functionality remains unchanged
- WebSocket support is automatically activated when WebSocket APIs are detected
- No breaking changes to CLI interface or configuration

Success criteria for the change
-------------------------------

✅ **Detection & Startup:**
- `sam local start-api` detects WebSocket APIs in template
- WebSocket server starts alongside HTTP server without errors
- Clear console output showing WebSocket endpoint (e.g., `ws://localhost:3001`)

✅ **Connection Lifecycle:**
- Clients can connect via `ws://localhost:PORT`
- `$connect` route invokes correct Lambda function on connection
- `$disconnect` route invokes correct Lambda function on disconnection
- Connection IDs are properly generated and tracked

✅ **Message Routing:**
- Custom routes (e.g., `sendMessage`) invoke correct Lambda functions
- Route selection expression (e.g., `$request.body.action`) is evaluated
- `$default` route handles unmatched messages

✅ **Lambda Integration:**
- Lambda functions receive proper WebSocket event format
- Lambda responses are sent back to WebSocket clients
- Lambda functions can call Management API to send messages

✅ **Management API:**
- `POST /@connections/{connectionId}` sends data to client
- `DELETE /@connections/{connectionId}` closes connection
- `GET /@connections/{connectionId}` returns connection info

✅ **Quality & Testing:**
- 94%+ unit test coverage maintained
- Integration tests for end-to-end WebSocket flows
- Existing HTTP/REST API tests continue to pass
- Works on Linux, macOS, and Windows

Out-of-Scope
------------

**Not Included in This Implementation:**
- WebSocket API deployment (use `sam deploy` - already works)
- WebSocket authorizers (Lambda or IAM) - can be added in future PR
- CloudWatch logs integration for WebSocket - can be added in future PR
- API Gateway WebSocket API stages/deployments - only local testing
- Connection throttling/rate limiting - unnecessary for local dev
- Binary message frame support - can be added if requested
- Subprotocol negotiation - can be added if requested

**Future Enhancements:**
- `sam local invoke` with WebSocket event templates
- WebSocket connection inspector/debugger UI
- Automatic reconnection testing utilities

User Experience Walkthrough
---------------------------

### Example 1: Starting WebSocket API

**Template (template.yaml):**
```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Resources:
  WebSocketApi:
    Type: AWS::ApiGatewayV2::Api
    Properties:
      Name: MyWebSocketAPI
      ProtocolType: WEBSOCKET
      RouteSelectionExpression: $request.body.action

  ConnectFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: index.handler
      Runtime: python3.11
      CodeUri: ./src

  ConnectRoute:
    Type: AWS::ApiGatewayV2::Route
    Properties:
      ApiId: !Ref WebSocketApi
      RouteKey: $connect
      Target: !Sub "integrations/${ConnectIntegration}"

  ConnectIntegration:
    Type: AWS::ApiGatewayV2::Integration
    Properties:
      ApiId: !Ref WebSocketApi
      IntegrationType: AWS_PROXY
      IntegrationUri: !GetAtt ConnectFunction.Arn
```

**Command:**
```bash
$ sam local start-api
```

**Output:**
```
Mounting ConnectFunction at http://127.0.0.1:3000/ [OPTIONS, GET, POST, ...] [REST]
Starting WebSocket API at ws://127.0.0.1:3001
WebSocket Routes:
  $connect -> ConnectFunction
  $disconnect -> DisconnectFunction
  sendMessage -> SendMessageFunction
  $default -> DefaultFunction

Press CTRL+C to quit
```

### Example 2: Testing WebSocket Connection

**JavaScript Client:**
```javascript
const ws = new WebSocket('ws://localhost:3001');

ws.onopen = () => {
  console.log('Connected!');
  ws.send(JSON.stringify({ action: 'sendMessage', message: 'Hello!' }));
};

ws.onmessage = (event) => {
  console.log('Received:', event.data);
};
```

**Lambda Function (Python):**
```python
import json
import boto3

def handler(event, context):
    route_key = event['requestContext']['routeKey']
    connection_id = event['requestContext']['connectionId']

    if route_key == '$connect':
        return {'statusCode': 200}

    elif route_key == 'sendMessage':
        body = json.loads(event['body'])

        # Use Management API to send message back
        apigw_management = boto3.client('apigatewaymanagementapi',
            endpoint_url='http://localhost:3001')

        apigw_management.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps({'echo': body['message']})
        )

        return {'statusCode': 200}
```

**Console Output:**
```
2025-01-24 10:15:32 WebSocket connection established: abc123def456
2025-01-24 10:15:32 Invoking ConnectFunction (python3.11)
2025-01-24 10:15:33 WebSocket message received: {"action": "sendMessage", "message": "Hello!"}
2025-01-24 10:15:33 Matched route: sendMessage -> SendMessageFunction
2025-01-24 10:15:33 Invoking SendMessageFunction (python3.11)
2025-01-24 10:15:34 Management API: POST /@connections/abc123def456
2025-01-24 10:15:34 Sent message to connection abc123def456
```

### Example 3: Specifying WebSocket Port

```bash
$ sam local start-api --port 3000 --websocket-port 8080
```

```
Starting REST/HTTP API at http://127.0.0.1:3000
Starting WebSocket API at ws://127.0.0.1:8080
```

Implementation
==============

CLI Changes
-----------

### New Options

Add optional CLI flag to `sam local start-api`:

```
--websocket-port INTEGER    Port to run WebSocket API on (default: auto-select)
```

**Behavior:**
- If not specified, WebSocket API uses `--port + 1`
- If WebSocket port conflicts, auto-increment until free port found
- Port selection logged to console for user visibility

### No Breaking Changes

- All existing options work unchanged
- WebSocket support is transparent - activates only when WebSocket API detected
- Default behavior unchanged for REST/HTTP APIs

Design
------

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ sam local start-api                                         │
│                                                             │
│  1. Parse template                                          │
│  2. Detect API types (REST, HTTP, WebSocket)                │
│  3. Create LocalApigwService (HTTP/REST)                    │
│  4. Create LocalWebSocketService (WebSocket) ← NEW          │
│  5. Start both servers concurrently                         │
└─────────────────────────────────────────────────────────────┘
                           │
                           ├─────────────┬─────────────────────┐
                           ▼             ▼                     ▼
                    ┌──────────┐  ┌──────────────┐  ┌──────────────────┐
                    │  Flask   │  │  WebSocket   │  │  Management API  │
                    │  Server  │  │  Server      │  │  (Flask)         │
                    │  (HTTP)  │  │  (asyncio)   │  │                  │
                    └────┬─────┘  └──────┬───────┘  └────────┬─────────┘
                         │               │                    │
                         └───────────────┴────────────────────┘
                                         │
                                         ▼
                              ┌────────────────────┐
                              │ LocalLambdaRunner  │
                              │ (Docker)           │
                              └────────────────────┘
```

### Component Design

#### 1. WebSocket API Detection

**File:** `samcli/lib/providers/cfn_api_provider.py`

**Changes:**
- Modify `_extract_cfn_gateway_v2_api()` (line 406)
- Check `properties.get("ProtocolType") == "WEBSOCKET"`
- Create separate WebSocket API object or flag in existing Api object

**Code Pattern:**
```python
def _extract_cfn_gateway_v2_api(self, ...):
    protocol_type = properties.get("ProtocolType", "HTTP")

    if protocol_type == "WEBSOCKET":
        # Collect WebSocket routes
        return self._process_websocket_api(...)
    elif protocol_type == "HTTP":
        # Existing HTTP API logic
        return self._process_http_api(...)
```

#### 2. WebSocket Route Collection

**File:** `samcli/local/apigw/route.py`

**Changes:**
- Add `WEBSOCKET = "WebSocketApi"` constant
- Support WebSocket route keys: `$connect`, `$disconnect`, `$default`, custom routes

**WebSocket Route Object:**
```python
Route(
    function_name="ConnectFunction",
    path="$connect",  # WebSocket route key
    methods=None,      # Not applicable for WebSocket
    event_type=Route.WEBSOCKET,
    payload_format_version=None,
    ...
)
```

#### 3. WebSocket Event Constructor

**New File:** `samcli/local/apigw/websocket_event_constructor.py`

**Function:** `construct_websocket_event(connection_id, route_key, body, request_context)`

**Output Format (AWS WebSocket Event):**
```python
{
    "requestContext": {
        "routeKey": "$connect",
        "eventType": "CONNECT",  # or MESSAGE, DISCONNECT
        "connectionId": "abc123def456",
        "apiId": "local-api-id",
        "domainName": "localhost",
        "stage": "$default",
        "requestId": "uuid",
        "requestTime": "24/Jan/2025:10:15:32 +0000",
        "requestTimeEpoch": 1706093732000
    },
    "body": "{...}",  # Message body (for MESSAGE events)
    "isBase64Encoded": false
}
```

#### 4. Connection Manager

**New File:** `samcli/local/apigw/websocket_connection_manager.py`

**Class:** `WebSocketConnectionManager`

**Responsibilities:**
- Generate unique connection IDs (UUID4)
- Store active WebSocket connections (thread-safe dict)
- Provide connection lookup for Management API
- Handle connection cleanup on disconnect

**Interface:**
```python
class WebSocketConnectionManager:
    def register_connection(self, websocket) -> str:
        """Returns connection_id"""

    def get_connection(self, connection_id) -> Optional[WebSocket]:
        """Returns WebSocket or None"""

    def remove_connection(self, connection_id):
        """Cleanup connection"""

    def list_connections(self) -> List[str]:
        """For debugging"""
```

#### 5. WebSocket Service

**New File:** `samcli/local/apigw/local_websocket_service.py`

**Class:** `LocalWebSocketService`

**Key Methods:**
- `__init__(api, lambda_runner, port, host, connection_manager)`
- `async start()`: Start WebSocket server
- `async handle_connection(websocket, path)`: Handle individual connection
- `async handle_message(connection_id, message)`: Route message to Lambda
- `_invoke_lambda(route_key, connection_id, body)`: Invoke Lambda function

**Implementation Pattern:**
```python
import asyncio
import websockets
import json
from threading import Thread

class LocalWebSocketService:
    def __init__(self, api, lambda_runner, port, host, connection_manager):
        self.api = api
        self.lambda_runner = lambda_runner
        self.port = port
        self.host = host
        self.connection_manager = connection_manager
        self.routes = self._build_route_map()

    async def handle_connection(self, websocket, path):
        connection_id = self.connection_manager.register_connection(websocket)

        try:
            # Invoke $connect
            await self._invoke_route("$connect", connection_id, None)

            # Handle messages
            async for message in websocket:
                await self.handle_message(connection_id, message)

        finally:
            # Invoke $disconnect
            await self._invoke_route("$disconnect", connection_id, None)
            self.connection_manager.remove_connection(connection_id)
```

#### 6. Management API Service

**New File:** `samcli/local/apigw/management_api_service.py`

**Endpoints:**
- `POST /@connections/{connectionId}` - Send message to connection
- `DELETE /@connections/{connectionId}` - Close connection
- `GET /@connections/{connectionId}` - Get connection info

**Implementation:**
```python
from flask import Flask, request, jsonify

class ManagementApiService:
    def __init__(self, connection_manager, port):
        self.app = Flask(__name__)
        self.connection_manager = connection_manager
        self.port = port
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route('/@connections/<connection_id>', methods=['POST'])
        def post_to_connection(connection_id):
            websocket = self.connection_manager.get_connection(connection_id)
            if not websocket:
                return jsonify({'message': 'GoneException'}), 410

            data = request.get_data()
            asyncio.run(websocket.send(data))
            return '', 200
```

#### 7. Service Orchestration

**File:** `samcli/commands/local/start_api/cli.py`

**Changes:**
- Detect WebSocket APIs in template
- Start WebSocket server in separate thread
- Share connection manager between WebSocket and Management API
- Handle graceful shutdown

**Pattern:**
```python
# In start_api command
if has_websocket_api:
    connection_manager = WebSocketConnectionManager()

    # Start WebSocket server in background thread
    ws_service = LocalWebSocketService(ws_api, lambda_runner, ws_port, host, connection_manager)
    ws_thread = Thread(target=ws_service.start)
    ws_thread.daemon = True
    ws_thread.start()

    # Start Management API
    mgmt_service = ManagementApiService(connection_manager, mgmt_port)
    mgmt_thread = Thread(target=mgmt_service.start)
    mgmt_thread.daemon = True
    mgmt_thread.start()

# Start HTTP server (blocks)
http_service.run()
```

### Threading Model

- **Main Thread**: HTTP/REST API (Flask) - blocks
- **Background Thread 1**: WebSocket server (asyncio event loop)
- **Background Thread 2**: Management API (Flask)
- **Shared State**: `WebSocketConnectionManager` (thread-safe with locks)

### Lambda Invocation

- Reuse existing `LocalLambdaRunner`
- Same Docker container management
- Different event format (WebSocket events vs HTTP events)
- Synchronous invocation (Lambda returns response)

``samconfig.toml`` Changes
--------------------------

No changes required. WebSocket support is transparent and requires no configuration.

**Optional Future Enhancement:**
```toml
[default.local_start_api.parameters]
websocket_port = 8080
```

Security
--------

### What new dependencies does this change require?

**Python Package: `websockets`**
- Version: `>=12.0`
- License: BSD-3-Clause (compatible with Apache 2.0)
- Maturity: Stable, widely used (20M+ downloads/month)
- Security: No known CVEs, actively maintained
- Purpose: WebSocket server implementation

**Justification:**
- Industry-standard Python WebSocket library
- Used by major projects (Sanic, channels, etc.)
- Pure Python, no C dependencies
- Full asyncio integration

### What other Docker container images are you using?

No new Docker images. Reuses existing Lambda runtime containers.

### Are you creating a new HTTP endpoint?

**Yes - Two New Endpoints:**

1. **WebSocket Endpoint** (`ws://localhost:{port}`)
   - **Purpose**: Accept WebSocket connections for local testing
   - **Security**: Binds to localhost only (127.0.0.1) by default
   - **Access**: Same as existing `sam local start-api` (local development only)

2. **Management API Endpoint** (`http://localhost:{port}/@connections/...`)
   - **Purpose**: Emulate API Gateway Management API for PostToConnection
   - **Security**: Binds to localhost only
   - **Access**: Only accessible from Lambda functions (local environment)

**Security Measures:**
- Default bind to 127.0.0.1 (localhost) prevents external access
- Same security model as existing `sam local start-api`
- No authentication (local dev environment, not production)
- Connection IDs are UUIDs (not guessable)

### Are you connecting to a remote API?

No. All services run locally.

### Are you reading/writing to a temporary folder?

No temporary files created. All state is in-memory (WebSocket connections, connection IDs).

### How do you validate new configuration?

No new configuration to validate. WebSocket support is auto-detected from template.

What is your Testing Plan (QA)?
===============================

Goal
----

Ensure WebSocket support:
1. Does not break existing HTTP/REST API functionality
2. Correctly handles WebSocket connection lifecycle
3. Routes messages to correct Lambda functions
4. Emulates API Gateway WebSocket behavior accurately
5. Maintains 94%+ code coverage

Pre-requisites
--------------

- Python 3.9+ environment
- Docker installed and running
- `websockets` library installed
- Sample WebSocket templates
- WebSocket client (wscat, JavaScript)

Test Scenarios/Cases
--------------------

### Unit Tests

**API Detection:**
- ✅ Detect WebSocket API with `ProtocolType: WEBSOCKET`
- ✅ Ignore WebSocket API with `ProtocolType: HTTP`
- ✅ Parse WebSocket routes ($connect, $disconnect, custom)
- ✅ Handle missing ProtocolType (default to HTTP)

**Event Construction:**
- ✅ Build $connect event with correct structure
- ✅ Build $disconnect event
- ✅ Build MESSAGE event with body
- ✅ Include proper requestContext fields
- ✅ Generate valid connection IDs

**Connection Management:**
- ✅ Register connection and return unique ID
- ✅ Retrieve connection by ID
- ✅ Remove connection on disconnect
- ✅ Handle concurrent connections (thread safety)

**Route Matching:**
- ✅ Match $connect route
- ✅ Match $disconnect route
- ✅ Match custom route from route selection expression
- ✅ Fall back to $default for unmatched routes
- ✅ Handle missing route selection expression

### Functional Tests

**WebSocket Service:**
- ✅ Start WebSocket server on specified port
- ✅ Accept WebSocket connections
- ✅ Invoke Lambda on $connect
- ✅ Route messages to correct Lambda
- ✅ Invoke Lambda on $disconnect
- ✅ Handle Lambda errors gracefully

**Management API:**
- ✅ POST /@connections/{id} sends message to client
- ✅ Return 410 for non-existent connection
- ✅ DELETE /@connections/{id} closes connection
- ✅ GET /@connections/{id} returns connection info

### Integration Tests

**End-to-End Flows:**
- ✅ Client connects → $connect Lambda invoked → connection established
- ✅ Client sends message → Lambda invoked → response received
- ✅ Lambda calls PostToConnection → client receives message
- ✅ Client disconnects → $disconnect Lambda invoked
- ✅ Multiple concurrent connections handled independently
- ✅ HTTP API and WebSocket API run simultaneously without interference

**Template Parsing:**
- ✅ Parse SAM template with WebSocket API
- ✅ Parse CloudFormation template with WebSocket API
- ✅ Handle mixed REST + WebSocket template
- ✅ Handle template with only WebSocket API

**Error Handling:**
- ✅ Lambda timeout in $connect → connection rejected
- ✅ Lambda error in message handler → error sent to client
- ✅ Invalid route selection → $default route invoked
- ✅ Connection closed during Lambda invocation → graceful cleanup

### Regression Tests

- ✅ All existing `sam local start-api` tests pass
- ✅ REST API functionality unchanged
- ✅ HTTP API functionality unchanged
- ✅ Templates without WebSocket API work normally

### Manual Testing

**With SmartAI Application:**
- ✅ SmartAI WebSocket client connects successfully
- ✅ Messages flow bidirectionally
- ✅ Connection lifecycle works correctly
- ✅ Performance acceptable for development use

Expected Results
----------------

### Unit Tests
- 94%+ code coverage for new files
- All assertions pass
- No test failures

### Integration Tests
- WebSocket connections successful
- Messages routed correctly
- Lambda invocations work
- Management API functional

### Regression Tests
- Zero failures in existing test suite
- No performance degradation
- No behavioral changes for HTTP/REST APIs

Pass/Fail
---------

**Pass Criteria:**
- ✅ All unit tests pass (94%+ coverage)
- ✅ All integration tests pass
- ✅ All regression tests pass
- ✅ Manual testing with SmartAI successful
- ✅ `make pr` succeeds
- ✅ No linting errors
- ✅ Code formatted with Black

**Fail Criteria:**
- ❌ Any existing test failures
- ❌ Coverage below 94%
- ❌ Breaking changes to HTTP/REST API
- ❌ WebSocket connections don't work
- ❌ Lambda invocations fail

Documentation Changes
=====================

### Code Documentation
- Docstrings for all new classes/methods (numpy format)
- Inline comments for complex logic
- Architecture diagram in design doc

### User Documentation
- Update README with WebSocket support mention
- Add WebSocket example templates
- Update `sam local start-api` help text

### Developer Documentation
- Update CLAUDE.md with WebSocket development guidance
- Create websocket_codebase_research.md
- Create websocket_implementation_plan.md

Open Issues
============

### Questions for Maintainers

1. **Port Selection**: Should WebSocket use same port as HTTP (with path-based routing) or separate port?
   - **Recommendation**: Separate port for simplicity (default: `--port + 1`)

2. **Feature Flag**: Should this be behind a beta feature flag initially?
   - **Recommendation**: No flag - transparent activation when WebSocket detected

3. **Python Version**: Requires `asyncio` - Python 3.7+ supported?
   - **Answer**: Yes, SAM CLI already requires 3.9+

4. **Windows Support**: Any known issues with `websockets` library on Windows?
   - **Action**: Test on Windows before finalizing PR

Task Breakdown
==============

- [ ] Send Pull Request with this design document
- [ ] Implement WebSocket detection in API providers
- [ ] Implement WebSocket event constructor
- [ ] Implement connection manager
- [ ] Implement WebSocket service
- [ ] Implement Management API service
- [ ] Update CLI command integration
- [ ] Unit tests (94%+ coverage)
- [ ] Functional tests
- [ ] Integration tests
- [ ] Regression tests (ensure existing tests pass)
- [ ] Manual testing with SmartAI application
- [ ] Run all tests on Windows
- [ ] Run all tests on macOS
- [ ] Run all tests on Linux
- [ ] Update README and user documentation
- [ ] Update developer documentation (CLAUDE.md)
- [ ] Code review and iterate
- [ ] Final PR submission to aws-sam-cli
