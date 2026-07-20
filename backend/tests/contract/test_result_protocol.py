import struct
from uuid import uuid4

import msgpack

from app.infrastructure.gpu.protocol import decode_result


def test_decodes_native_worker_result_contract():
    request_id = str(uuid4())
    payload = msgpack.packb(
        {
            "protocol_version": 1,
            "request_id": request_id,
            "status": "OK",
            "error_code": "",
            "faces": [
                {
                    "ordinal": 0,
                    "x": 1.0,
                    "y": 2.0,
                    "width": 3.0,
                    "height": 4.0,
                    "landmarks_xy": [float(value) for value in range(10)],
                    "detector_confidence": 0.9,
                    "embedding": [1.0] + [0.0] * 511,
                    "aligned_jpeg": b"jpeg",
                }
            ],
        },
        use_bin_type=True,
    )

    result = decode_result(struct.pack("!I", len(payload)) + payload)

    assert result.request_id == request_id
    assert result.faces[0].landmarks_xy == tuple(float(value) for value in range(10))
    assert len(result.faces[0].embedding) == 512
