"""เก็บ snapshot และ state เป็น JSON ใน Blob (หรือโฟลเดอร์ในเครื่องตอนทดสอบ)"""
from __future__ import annotations

import json
from pathlib import Path


class LocalStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, name: str):
        p = self.root / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, name: str, obj) -> None:
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


class BlobStore:
    def __init__(self, connection_string: str, container: str = "tag-governance"):
        from azure.storage.blob import BlobServiceClient

        svc = BlobServiceClient.from_connection_string(connection_string)
        self.container = svc.get_container_client(container)
        if not self.container.exists():
            self.container.create_container()

    def get(self, name: str):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            data = self.container.download_blob(name).readall()
        except ResourceNotFoundError:
            return None
        return json.loads(data.decode("utf-8"))

    def put(self, name: str, obj) -> None:
        self.container.upload_blob(name, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"), overwrite=True)
