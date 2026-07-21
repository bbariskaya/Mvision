from pathlib import Path

from scripts.import_friends_dataset import import_dataset


class _Response:
    def __init__(self, face_id: str):
        self._face_id = face_id

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"faces": [{"faceId": self._face_id}]}


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], str]] = []

    def post(self, url: str, *, data: dict[str, str], files: dict) -> _Response:
        filename = files["image"][0]
        self.calls.append((url, data, filename))
        return _Response(data.get("faceId", f"face-{data['name'].lower()}"))


def test_import_dataset_reuses_actor_identity_and_ignores_non_images(tmp_path: Path) -> None:
    for actor in ("Chandler", "Joey"):
        actor_dir = tmp_path / actor
        actor_dir.mkdir()
        (actor_dir / "b.jpg").write_bytes(b"jpg")
        (actor_dir / "a.png").write_bytes(b"png")
        (actor_dir / "notes.txt").write_text("ignore")
    client = _Client()

    counts = import_dataset(tmp_path, "http://friends", client)

    assert counts == {"Chandler": 2, "Joey": 2}
    assert [call[2] for call in client.calls] == ["a.png", "b.jpg", "a.png", "b.jpg"]
    assert client.calls[0][1] == {"name": "Chandler"}
    assert client.calls[1][1]["faceId"] == "face-chandler"
    assert client.calls[2][1] == {"name": "Joey"}


def test_import_dataset_can_hold_out_last_image_per_actor(tmp_path: Path) -> None:
    actor_dir = tmp_path / "Rachel"
    actor_dir.mkdir()
    (actor_dir / "a.jpg").write_bytes(b"a")
    (actor_dir / "b.jpg").write_bytes(b"b")
    client = _Client()

    counts = import_dataset(tmp_path, "http://friends", client, holdout_last=True)

    assert counts == {"Rachel": 1}
    assert [call[2] for call in client.calls] == ["a.jpg"]
