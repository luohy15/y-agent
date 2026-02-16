from typing import Optional, List, Dict, Union
from storage.entity.dto import Message
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp

def create_message(role: str, content: str, reasoning_content: Optional[str] = None, provider: Optional[str] = None,
                   model: Optional[str] = None, id: Optional[str] = None, reasoning_effort: Optional[float] = None,
                   server: Optional[str] = None, tool: Optional[str] = None, arguments: Optional[Dict[str, Union[str, int, float, bool, Dict, List]]] = None,
                   links: Optional[List[str]] = None) -> Message:
    """Create a Message object with optional fields."""
    message_data = {
        "role": role,
        "content": content,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": get_unix_timestamp()
    }

    if reasoning_content is not None:
        message_data["reasoning_content"] = reasoning_content

    if provider is not None:
        message_data["provider"] = provider

    if model is not None:
        message_data["model"] = model

    if id is not None:
        message_data["id"] = id

    if reasoning_effort is not None:
        message_data["reasoning_effort"] = reasoning_effort

    if server is not None:
        message_data["server"] = server

    if tool is not None:
        message_data["tool"] = tool

    if arguments is not None:
        message_data["arguments"] = arguments

    if links is not None:
        message_data["links"] = links

    return Message.from_dict(message_data)
