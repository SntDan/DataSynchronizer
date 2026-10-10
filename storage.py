"""Replace small editable files only after their new contents are complete."""

import os
import tempfile
from pathlib import Path


def write_text_atomic(path, text):
    path = Path(path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}-", suffix=".tmp", delete=False,
        ) as file_obj:
            temporary_path = Path(file_obj.name)
            file_obj.write(text)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
