# Streaming Observability Design

Date: 2026-05-27

## Goal

Measure streaming request completion accurately and record late generator failures for SSE/chat streaming endpoints.

## Chosen Approach

Replace the current `BaseHTTPMiddleware` request observability implementation with an ASGI middleware. The middleware will wrap `send` so it can observe the final `http.response.body` frame and only record successful completion when the response has actually finished streaming.

This keeps the existing app-native ops foundation:

```text
X-Request-ID response header
structured JSON request logs
in-memory metrics snapshot
/metrics admin-key protection
/ready HTTP 503 when not ready
```

## Completion Semantics

For non-streaming requests, behavior stays effectively the same: record once the full body has been sent.

For streaming requests, record completion only when Starlette sends:

```text
type=http.response.body
more_body=false
```

That makes `duration_ms` represent the full stream lifetime instead of the time required to construct the response object.

## Error Semantics

If the application raises before response headers are sent, the middleware records a failed request with status `500`, logs `event=request_failed`, and re-raises.

If a streaming body raises after headers have been sent, the middleware records:

```text
event=request_failed
status_code=<started response status, usually 200>
stream_error=true
error=<exception type>
```

It increments `errors_total` and re-raises so the ASGI server/client sees the stream failure. The status code cannot be changed after response start, so the failure signal lives in logs and metrics.

If an app-level streaming endpoint catches an exception and converts it into an SSE
`error` event, the endpoint must mark the request with handled stream error metadata before
yielding the error event. The middleware reads that marker at the final body frame and records
the request as:

```text
event=request_failed
stream_error=true
handled=true
status_code=<started response status, usually 200>
```

Client disconnects and cancellation errors are recorded as stream failures when they reach
the middleware, then re-raised.

## Headers

The middleware injects `X-Request-ID` into `http.response.start`. This ensures regular and streaming responses both include the same request id. The existing exception handler remains as fallback for framework-generated 500 responses.

## Metrics

The metrics store keeps the current shape. Streaming late failures are recorded as request metrics with `error=true`; the status code remains the status that was sent to the client if headers had already started.

## Testing

Unit tests will cover:

```text
streaming duration includes body iteration time
streaming completion is recorded once after the final body frame
late streaming generator errors increment errors_total
late streaming generator errors log request_failed with stream_error=true
handled /chat/stream SSE error events increment errors_total
stream cancellations increment errors_total
regular request behavior and request id propagation remain intact
```

Full verification will use local unit tests, lint/type checks, Docker-backed tests, Docker e2e, and `make ops-check`.
