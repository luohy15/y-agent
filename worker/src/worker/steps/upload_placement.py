"""VM script: public code in argv, all transfer inputs (including URL) on stdin."""

PLACEMENT_SCRIPT = r'''
import base64
import fcntl
import hashlib
import json
import os
import stat
import sys
import time
import urllib.request


def digest(path):
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        for block in iter(lambda: stream.read(262144), b""):
            h.update(block)
    return base64.b64encode(h.digest()).decode()


def matches(path, job):
    try:
        info = os.lstat(path)
        return (stat.S_ISREG(info.st_mode) and info.st_size == job["size_bytes"]
                and digest(path) == job["expected_checksum_sha256_b64"])
    except FileNotFoundError:
        return False


def place(job):
    directory = os.path.expanduser(job["dest_dir"])
    try:
        os.makedirs(directory, exist_ok=True)
    except (NotADirectoryError, FileExistsError):
        return "not_a_directory"
    part = None
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        prefix = ".yupload." + job["upload_id"] + "."
        for entry in os.scandir(directory):
            if entry.name.startswith(prefix) and entry.name.endswith(".part"):
                try:
                    if entry.stat(follow_symlinks=False).st_mtime < time.time() - 900:
                        os.unlink(entry.path)
                except FileNotFoundError:
                    pass
        destination = os.path.join(directory, job["filename"])
        if matches(destination, job):
            return "already_placed"
        if not job["overwrite_ack"]:
            try:
                os.lstat(destination)
            except FileNotFoundError:
                pass
            else:
                return "destination_changed"
        part_path = os.path.join(directory, prefix + job["lease_token"] + ".part")
        fd = os.open(part_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        part = part_path
        h = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as output:
            with urllib.request.urlopen(job["url"], timeout=60) as response:
                while True:
                    block = response.read(262144)
                    if not block:
                        break
                    size += len(block)
                    if size > job["size_bytes"]:
                        return "error"
                    h.update(block)
                    output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if size != job["size_bytes"] or base64.b64encode(h.digest()).decode() != job["expected_checksum_sha256_b64"]:
            return "error"
        if job["overwrite_ack"]:
            os.replace(part, destination)
        else:
            try:
                os.link(part, destination)
            except FileExistsError:
                return "already_placed" if matches(destination, job) else "destination_changed"
        os.fsync(directory_fd)
        return "saved"
    finally:
        if part is not None:
            try:
                os.unlink(part)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


try:
    result = place(json.load(sys.stdin))
except NotADirectoryError:
    result = "not_a_directory"
except Exception:
    result = "error"
print(json.dumps({"result": result, "detail": ""}))
'''
