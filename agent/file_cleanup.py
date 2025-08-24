import os
from datetime import datetime

from .utils import uploaded_files


def cleanup_old_files():
    """Clean up files older than 1 hour."""
    current_time = datetime.now()
    files_to_remove = []

    for file_id, file_info in uploaded_files.items():
        if (current_time - file_info["uploaded_at"]).seconds > 3600:  # 1 hour
            files_to_remove.append(file_id)

    for file_id in files_to_remove:
        file_info = uploaded_files[file_id]
        try:
            if os.path.exists(file_info["path"]):
                os.unlink(file_info["path"])
        except Exception:
            pass
        del uploaded_files[file_id]