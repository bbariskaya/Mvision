# Phase 1 — API Contract (Sprint 01 Design Only)

Base path: `/api/v1`.

## Result per face

```json
{
  "faceId": "<uuid>",
  "status": "known | anonymous | new_anonymous",
  "name": "string | null",
  "metadata": { },
  "boundingBox": { "x": 0, "y": 0, "width": 0, "height": 0 },
  "confidence": 0.0
}
```

## Common response wrapper

```json
{
  "processId": "<uuid>",
  "faceCount": 1,
  "faces": [ /* per-face result */ ]
}
```

## Endpoints

### `POST /api/v1/faces/recognize`
Multipart upload of an encoded image.

Success example:

```json
{
  "processId": "0190...",
  "faceCount": 2,
  "faces": [
    { "faceId": "0191...", "status": "known", "name": "Ada", "metadata": {}, "boundingBox": {...}, "confidence": 0.91 },
    { "faceId": "0192...", "status": "anonymous", "name": null, "metadata": null, "boundingBox": {...}, "confidence": 0.78 }
  ]
}
```

No-face success:

```json
{
  "processId": "0193...",
  "faceCount": 0,
  "faces": []
}
```

### `POST /api/v1/faces/enroll`
Enroll/name an existing anonymous face or a new sample.

Request:

```json
{
  "faceId": "0191...",
  "name": "Ada",
  "metadata": { "department": "eng" }
}
```

### `GET /api/v1/faces/{faceId}`
Returns persistent identity state and latest metadata.

### `PATCH /api/v1/faces/{faceId}`
Update known identity name/metadata. Same `faceId` preserved.

### `DELETE /api/v1/faces/{faceId}`
Soft-delete/inactive lifecycle. History retained.

### `GET /api/v1/faces/{faceId}/history`
Returns process IDs and timestamps where this `faceId` appeared.

### `GET /api/v1/processes/{processId}`
Returns process details, recognition results, and events.

## Errors
Standardized error envelope with sanitized `code`, `message`, `processId` if available. No stack traces, SQL, secrets, or local paths.
