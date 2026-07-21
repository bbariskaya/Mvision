from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.presentation.dependencies import (
    get_enrollment_service,
    get_identity_service,
    get_process_service,
    get_recognition_service,
)

FACE_ID = str(uuid4())
PROCESS_ID = str(uuid4())


def _jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1, 1), color=(127, 127, 127)).save(output, format="JPEG")
    return output.getvalue()


JPEG = _jpeg()
NOW = datetime.now(UTC).isoformat()


def face_result():
    return {
        "face_id": FACE_ID,
        "status": "known",
        "name": "Ada",
        "metadata": {"department": "eng"},
        "bounding_box": {"x": 1, "y": 2, "width": 3, "height": 4},
        "confidence": 0.91,
    }


class FakeRecognition:
    async def recognize(self, image, process_id=None):
        return {"process_id": PROCESS_ID, "face_count": 1, "faces": [face_result()]}

    async def reject(self, process_id, code):
        return None


class FakeEnrollment:
    @staticmethod
    def parse_metadata(raw):
        return {"department": "eng"}

    async def enroll(self, image, name, metadata, face_id=None, process_id=None):
        return {"process_id": PROCESS_ID, "face_count": 1, "faces": [face_result()]}

    async def reject(self, process_id, code):
        return None


class FakeIdentities:
    async def get(self, face_id):
        return {
            "face_id": FACE_ID,
            "status": "known",
            "name": "Ada",
            "metadata": {},
            "is_active": True,
            "sample_count": 2,
            "created_at": NOW,
            "updated_at": NOW,
        }

    async def update(self, face_id, name, metadata):
        value = await self.get(face_id)
        value["process_id"] = PROCESS_ID
        value["name"] = name
        return value

    async def delete(self, face_id):
        return {"process_id": PROCESS_ID, "face_id": FACE_ID, "deleted": True}

    async def history(self, face_id):
        return {
            "face_id": FACE_ID,
            "history": [{"process_id": PROCESS_ID, "timestamp": NOW, "status": "known"}],
        }


class FakeProcesses:
    async def get(self, process_id):
        return {
            "process_id": PROCESS_ID,
            "process_type": "recognize",
            "status": "completed",
            "face_count": 1,
            "error_code": None,
            "created_at": NOW,
            "completed_at": NOW,
            "faces": [face_result()],
            "events": [],
        }


def client():
    app.dependency_overrides[get_recognition_service] = lambda: FakeRecognition()
    app.dependency_overrides[get_enrollment_service] = lambda: FakeEnrollment()
    app.dependency_overrides[get_identity_service] = lambda: FakeIdentities()
    app.dependency_overrides[get_process_service] = lambda: FakeProcesses()
    return TestClient(app)


def test_recognize_contract_uses_required_camel_case_fields():
    response = client().post(
        "/api/v1/faces/recognize", files={"image": ("face.jpg", JPEG, "image/jpeg")}
    )
    assert response.status_code == 200
    assert response.json() == {
        "processId": PROCESS_ID,
        "faceCount": 1,
        "faces": [
            {
                "faceId": FACE_ID,
                "status": "known",
                "name": "Ada",
                "metadata": {"department": "eng"},
                "boundingBox": {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0},
                "confidence": 0.91,
            }
        ],
    }


def test_enroll_accepts_image_name_metadata_and_optional_face_id():
    response = client().post(
        "/api/v1/faces/enroll",
        files={"image": ("face.jpg", JPEG, "image/jpeg")},
        data={"name": "Ada", "metadata": '{"department":"eng"}', "faceId": FACE_ID},
    )
    assert response.status_code == 201
    assert response.json()["faces"][0]["faceId"] == FACE_ID


def test_identity_history_and_process_contracts():
    api = client()
    assert api.get(f"/api/v1/faces/{FACE_ID}").status_code == 200
    assert api.patch(
        f"/api/v1/faces/{FACE_ID}", json={"name": "Ada", "metadata": {}}
    ).json()["processId"] == PROCESS_ID
    assert api.get(f"/api/v1/faces/{FACE_ID}/history").json()["history"][0][
        "processId"
    ] == PROCESS_ID
    assert api.get(f"/api/v1/processes/{PROCESS_ID}").json()["faceCount"] == 1
    assert api.delete(f"/api/v1/faces/{FACE_ID}").json()["deleted"] is True


def teardown_module():
    app.dependency_overrides.clear()
