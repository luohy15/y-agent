"""Channel writes serialize on advisory lock 4400,1."""

import hashlib


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()
