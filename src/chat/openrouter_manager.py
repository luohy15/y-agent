from typing import List, Dict, Optional, AsyncGenerator, Union
import json
from types import SimpleNamespace
import httpx
from cli.display_manager import DisplayManager
from util import get_iso8601_timestamp, get_unix_timestamp
from config import config
from chat.models import Message

class OpenRouterManager:
    def __init__(self, bot_config):
        """Initialize OpenRouter settings.

        Args:
            bot_config: Bot configuration containing API settings
        """
        self.api_key = bot_config.api_key
        self.base_url = bot_config.base_url
        self.model = bot_config.model
        self.display_manager = None

    def set_display_manager(self, display_manager: DisplayManager):
        """Set the display manager for streaming responses"""
        self.display_manager = display_manager

    def create_message(self, role: str, content: str, reasoning_content: Optional[str] = None, provider: Optional[str] = None, model: Optional[str] = None) -> Message:
        """Create a Message object with optional timestamps, provider, and model.

        Args:
            role: Message role (user/assistant/system)
            content: Message content
            reasoning_content: Optional reasoning content
            provider: Optional provider of the message
            model: Optional model used to generate the message

        Returns:
            Message: Message object with role, content, and optional fields
        """
        message_data = {
            "role": role,
            "content": content
        }

        message_data.update({
            "timestamp": get_iso8601_timestamp(),
            "unix_timestamp": get_unix_timestamp()
        })

        if reasoning_content is not None:
            message_data["reasoning_content"] = reasoning_content

        if provider is not None:
            message_data["provider"] = provider

        if model is not None:
            message_data["model"] = model

        return Message.from_dict(message_data)

    def prepare_messages_for_completion(self, messages: List[Message], system_prompt: Optional[str] = None) -> List[Dict]:
        """Prepare messages for completion by adding system message and cache_control.

        Args:
            messages: Original list of Message objects
            system_prompt: Optional system message to add at the start

        Returns:
            List[Dict]: New message list with system message and cache_control added
        """
        # Create new list starting with system message if provided
        prepared_messages = []
        if system_prompt:
            system_message = self.create_message("system", system_prompt)
            system_message_dict = system_message.to_dict()
            if isinstance(system_message_dict["content"], str):
                system_message_dict["content"] = [{"type": "text", "text": system_message_dict["content"]}]
            # add cache_control only to claude-3 series model
            if "claude-3" in self.model:
                for part in system_message_dict["content"]:
                    if part.get("type") == "text":
                        part["cache_control"] = {"type": "ephemeral"}
            prepared_messages.append(system_message_dict)

        # Add original messages
        for msg in messages:
            msg_dict = msg.to_dict()
            if isinstance(msg_dict["content"], list):
                msg_dict["content"] = [dict(part) for part in msg_dict["content"]]
            prepared_messages.append(msg_dict)

        # Find last user message
        if "claude-3" in self.model:
            for msg in reversed(prepared_messages):
                if msg["role"] == "user":
                    if isinstance(msg["content"], str):
                        msg["content"] = [{"type": "text", "text": msg["content"]}]
                    # Add cache_control to last text part
                    text_parts = [part for part in msg["content"] if part.get("type") == "text"]
                    if text_parts:
                        last_text_part = text_parts[-1]
                    else:
                        last_text_part = {"type": "text", "text": "..."}
                        msg["content"].append(last_text_part)
                    last_text_part["cache_control"] = {"type": "ephemeral"}
                    break

        return prepared_messages

    async def call_chat_completions(self, messages: List[Message], system_prompt: Optional[str] = None) -> Message:
        """Get a streaming chat response from OpenRouter.

        Args:
            messages: List of Message objects
            system_prompt: Optional system prompt to add at the start

        Returns:
            Message: The assistant's response message

        Raises:
            Exception: If API call fails
        """
        # Prepare messages with cache_control and system message
        prepared_messages = self.prepare_messages_for_completion(messages, system_prompt)
        # TODO: get provider config from bot config
        provider_config = None
        body = {
            "model": self.model,
            "messages": prepared_messages,
            "stream": True
        }
        if provider_config:
            body["provider"] = provider_config
        if "deepseek-r1" in self.model:
            body["include_reasoning"] = True
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url
            ) as client:
                async with client.stream(
                    "POST",
                    "/chat/completions",
                    headers={
                        "HTTP-Referer": "https://luohy15.com",
                        'X-Title': 'y-cli',
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=60.0
                ) as response:
                    response.raise_for_status()

                    if not self.display_manager:
                        raise Exception("Display manager not set for streaming response")

                    # Store provider and model info from first response chunk
                    provider = None
                    model = None

                    async def generate_chunks():
                        nonlocal provider, model
                        async for chunk in response.aiter_lines():
                            if chunk.startswith("data: "):
                                try:
                                    data = json.loads(chunk[6:])
                                    # Extract provider and model from first chunk that has them
                                    if provider is None and data.get("provider"):
                                        provider = data["provider"]
                                    if model is None and data.get("model"):
                                        model = data["model"]

                                    if data.get("choices"):
                                        delta = data["choices"][0].get("delta", {})
                                        content = delta.get("content")
                                        reasoning_content = delta.get("reasoning")
                                        if content is not None or reasoning_content is not None:
                                            chunk_data = SimpleNamespace(
                                                choices=[SimpleNamespace(
                                                    delta=SimpleNamespace(content=content, reasoning_content=reasoning_content)
                                                )],
                                                model=model,
                                                provider=provider
                                            )
                                            yield chunk_data
                                except json.JSONDecodeError:
                                    continue
                    content_full, reasoning_content_full = await self.display_manager.stream_response(generate_chunks())
                    # build assistant message
                    assistant_message = self.create_message(
                        "assistant",
                        content_full,
                        reasoning_content=reasoning_content_full,
                        provider=provider,
                        model=model
                    )
                    return assistant_message

        except httpx.HTTPError as e:
            raise Exception(f"HTTP error getting chat response: {str(e)}")
        except Exception as e:
            raise Exception(f"Error getting chat response: {str(e)}")

    def contains_tool_use(self, content: str) -> bool:
        """Check if content contains tool use XML tags"""
        tool_tags = [
            "use_mcp_tool",
            "access_mcp_resource"
        ]

        for tag in tool_tags:
            if f"<{tag}>" in content and f"</{tag}>" in content:
                return True
        return False

    def split_content(self, content: str) -> tuple[str, Optional[str]]:
        """Split content into plain text and tool definition parts.

        Args:
            content: The content to split

        Returns:
            Tuple of (plain content, tool content)
        """
        tool_tags = [
            "use_mcp_tool",
            "access_mcp_resource"
        ]

        # Find the first tool tag
        first_tag_index = len(content)
        first_tag = None
        for tag in tool_tags:
            tag_start = content.find(f"<{tag}>")
            if tag_start != -1 and tag_start < first_tag_index:
                first_tag_index = tag_start
                first_tag = tag

        if first_tag_index < len(content) and first_tag:
            # Find the end of the tool block
            end_tag = f"</{first_tag}>"
            end_index = content.find(end_tag, first_tag_index)
            if end_index != -1:
                end_index += len(end_tag)

                # Extract tool content
                tool_content = content[first_tag_index:end_index].strip()

                # Combine content before and after tool block
                plain_content = (content[:first_tag_index] + content[end_index:]).strip()

                return plain_content, tool_content

        return content.strip(), None
