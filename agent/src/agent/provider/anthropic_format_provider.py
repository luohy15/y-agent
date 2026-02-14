import json
from typing import List, Dict, Optional
from .base_provider import BaseProvider
import httpx
from storage.entity.dto import Message, BotConfig
from agent.loop import ClientError


class AnthropicFormatProvider(BaseProvider):
    def __init__(self, bot_config: BotConfig):
        self.bot_config = bot_config

    def _convert_messages(self, messages: List[Message], system_prompt: Optional[str] = None) -> tuple[Optional[str], List[Dict]]:
        """Convert internal messages to Anthropic Messages API format.

        Returns (system, messages) tuple.
        """
        system = system_prompt or None

        result = []
        for msg in messages:
            msg_dict = msg.to_dict()
            role = msg_dict["role"]

            if role == "system":
                # Anthropic uses system as a top-level param
                system = msg_dict["content"] if isinstance(msg_dict["content"], str) else " ".join(
                    p["text"] for p in msg_dict["content"] if p.get("type") == "text"
                )
                continue

            if role == "assistant":
                content_blocks = []
                text_content = msg_dict.get("content", "")
                if text_content:
                    content_blocks.append({"type": "text", "text": text_content})

                # Add tool_use blocks from tool calls
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        try:
                            tool_input = json.loads(tc["function"]["arguments"])
                        except (json.JSONDecodeError, TypeError):
                            tool_input = {}
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": tool_input,
                        })

                result.append({"role": "assistant", "content": content_blocks or [{"type": "text", "text": ""}]})

            elif role == "tool":
                tool_call_id = msg.tool_call_id or "unknown"
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": msg_dict.get("content", ""),
                    }],
                })

            elif role == "user":
                content = msg_dict.get("content", "")
                if isinstance(content, str):
                    result.append({"role": "user", "content": content})
                else:
                    result.append({"role": "user", "content": content})

        # Merge consecutive same-role messages (Anthropic requires alternating roles)
        merged = []
        for msg in result:
            if merged and merged[-1]["role"] == msg["role"]:
                prev_content = merged[-1]["content"]
                curr_content = msg["content"]
                # Normalize to list
                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{"type": "text", "text": curr_content}]
                merged[-1]["content"] = prev_content + curr_content
            else:
                merged.append(msg)

        return system, merged

    def _convert_tools(self, openai_tools: List[Dict]) -> List[Dict]:
        """Convert OpenAI-format tool definitions to Anthropic format."""
        anthropic_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                })
        return anthropic_tools

    async def call_chat_completions_non_stream(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        tools: Optional[list] = None,
    ) -> dict:
        """Get a non-streaming chat response from Anthropic Messages API."""
        system, prepared_messages = self._convert_messages(messages, system_prompt)

        body: Dict = {
            "model": self.bot_config.model,
            "messages": prepared_messages,
            "max_tokens": self.bot_config.max_tokens or 8192,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = self._convert_tools(tools)

        base_url = self.bot_config.base_url.rstrip("/")

        try:
            async with httpx.AsyncClient(base_url=base_url) as client:
                response = await client.post(
                    self.bot_config.custom_api_path or "/v1/messages",
                    headers={
                        "x-api-key": self.bot_config.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()

                # Parse Anthropic response into our standard format
                content_text = ""
                tool_calls = []

                for block in data.get("content", []):
                    if block["type"] == "text":
                        content_text += block["text"]
                    elif block["type"] == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        })

                return {
                    "content": content_text or None,
                    "tool_calls": tool_calls if tool_calls else None,
                    "provider": self.bot_config.name,
                    "model": data.get("model", self.bot_config.model),
                }
        except httpx.HTTPStatusError as e:
            body = e.response.text if e.response else ""
            if 400 <= e.response.status_code < 500:
                raise ClientError(f"HTTP {e.response.status_code}: {body}") from e
            raise Exception(f"HTTP error getting chat response: {str(e)}")
        except httpx.HTTPError as e:
            raise Exception(f"HTTP error getting chat response: {str(e)}")
        except Exception as e:
            if "HTTP error" in str(e) or isinstance(e, ClientError):
                raise
            raise Exception(f"Error getting chat response: {str(e)}")
