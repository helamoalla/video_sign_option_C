import uuid
from pathlib import Path

def create_file_path(folder: str, extension: str):
    Path(folder).mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.{extension}"
    return str(Path(folder) / filename)