# Phase 1 — PostgreSQL ERD

```mermaid
erDiagram
    FACE_IDENTITY ||--o{ FACE_SAMPLE : owns
    FACE_IDENTITY ||--o{ RECOGNITION_RESULT : appears_as
    PROCESS_RECORD ||--o{ RECOGNITION_RESULT : contains
    PROCESS_RECORD ||--o{ PROCESS_EVENT : logs

    FACE_IDENTITY {
        uuid face_id PK
        string lifecycle_status
        string name nullable
        jsonb metadata
        boolean is_active
        int version
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at nullable
    }
    FACE_SAMPLE {
        uuid sample_id PK
        uuid face_id FK
        string lifecycle_state
        string bucket
        string object_key
        string media_type
        string sha256
        string detector_version
        string embedding_model_version
        string alignment_version
        string preprocess_version
        jsonb bounding_box
        jsonb landmarks nullable
        jsonb quality nullable
        string failure_code nullable
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at nullable
    }
    PROCESS_RECORD {
        uuid process_id PK
        string process_type
        string status
        int face_count
        string error_code nullable
        timestamptz created_at
        timestamptz completed_at nullable
    }
    RECOGNITION_RESULT {
        uuid result_id PK
        uuid process_id FK
        int detection_ordinal
        uuid face_id FK
        string status_snapshot
        string name_snapshot nullable
        jsonb metadata_snapshot
        jsonb bounding_box
        float detector_confidence
        float match_confidence
        uuid matched_sample_id nullable FK
        timestamptz created_at
    }
    PROCESS_EVENT {
        uuid event_id PK
        uuid process_id FK
        string event_type
        jsonb sanitized_details
        timestamptz created_at
    }
```

## Constraints and States

| Table | Check / Unique |
|-------|----------------|
| `face_identity` | `lifecycle_status IN ('anonymous','known')`; known requires non-empty name; anonymous requires name NULL and metadata `'{}'`; `(lifecycle_status, is_active)` index |
| `face_sample` | `lifecycle_state IN ('pending','blob_ready','indexed','active','inactive','failed')`; `(bucket, object_key)` unique; FK to `face_identity` |
| `process_record` | `process_type IN ('recognize','enroll','update','delete')`; `status IN ('started','completed','failed')` |
| `recognition_result` | `(process_id, detection_ordinal)` unique; `status_snapshot IN ('known','anonymous','new_anonymous')`; immutable after insert |
| `process_event` | FK `process_record` CASCADE; best-effort log |

## Requirement-to-Column Mapping

| Requirement | Tables / Columns |
|-------------|------------------|
| Persistent faceId | `face_identity.face_id` |
| Anonymous vs known | `face_identity.lifecycle_status`, `name`, `metadata` |
| Multiple samples per face | `face_sample.face_id FK` |
| Process trackability | `process_record.process_id`, `status`, `face_count` |
| Process logging | `process_event.process_id`, `event_type`, `sanitized_details` |
| History / immutable snapshots | `recognition_result.*`, no UPDATE API |
