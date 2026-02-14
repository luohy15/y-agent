from typing import List, Dict, Optional
from .base_provider import BaseProvider
import httpx
from storage.entity.dto import Message, BotConfig
from agent.loop import ClientError
from ..utils.message_utils import create_message

class OpenAIFormatProvider(BaseProvider):
    def __init__(self, bot_config: BotConfig):
        self.bot_config = bot_config

    def prepare_messages_for_completion(self, messages: List[Message], system_prompt: Optional[str] = None) -> List[Dict]:
        """Prepare messages for completion by adding system message and cache_control."""
        prepared_messages = []
        if system_prompt:
            system_message = create_message('system', system_prompt)
            system_message_dict = system_message.to_dict()
            if isinstance(system_message_dict["content"], str):
                system_message_dict["content"] = [{"type": "text", "text": system_message_dict["content"]}]
            system_message_dict.pop("timestamp", None)
            system_message_dict.pop("unix_timestamp", None)
            if "claude-3" in self.bot_config.model:
                for part in system_message_dict["content"]:
                    if part.get("type") == "text":
                        part["cache_control"] = {"type": "ephemeral"}
            prepared_messages.append(system_message_dict)

        for msg in messages:
            msg_dict = msg.to_dict()
            if isinstance(msg_dict["content"], list):
                msg_dict["content"] = [dict(part) for part in msg_dict["content"]]
            msg_dict.pop("timestamp", None)
            msg_dict.pop("unix_timestamp", None)
            prepared_messages.append(msg_dict)

        if "claude-3" in self.bot_config.model:
            for msg in reversed(prepared_messages):
                if msg["role"] == "user":
                    if isinstance(msg["content"], str):
                        msg["content"] = [{"type": "text", "text": msg["content"]}]
                    text_parts = [part for part in msg["content"] if part.get("type") == "text"]
                    if text_parts:
                        last_text_part = text_parts[-1]
                    else:
                        last_text_part = {"type": "text", "text": "..."}
                        msg["content"].append(last_text_part)
                    last_text_part["cache_control"] = {"type": "ephemeral"}
                    break

        return prepared_messages

    def prepare_messages_for_api(self, messages: List[Message], system_prompt: Optional[str] = None) -> List[Dict]:
        """Prepare messages for API, handling tool_calls and tool results."""
        prepared = self.prepare_messages_for_completion(messages, system_prompt)

        result = []
        for i, msg_dict in enumerate(prepared):
            for key in ["id", "parent_id", "tool", "arguments", "server",
                        "reasoning_content", "reasoning_effort", "links", "images", "model", "provider"]:
                msg_dict.pop(key, None)

            orig_msg = None
            offset = 1 if system_prompt else 0
            orig_idx = i - offset
            if 0 <= orig_idx < len(messages):
                orig_msg = messages[orig_idx]

            if orig_msg and orig_msg.tool_calls:
                msg_dict["tool_calls"] = orig_msg.tool_calls
                if not msg_dict.get("content"):
                    msg_dict["content"] = ""
            if orig_msg and orig_msg.tool_call_id:
                msg_dict["tool_call_id"] = orig_msg.tool_call_id

            result.append(msg_dict)
        return result

    async def call_chat_completions_non_stream(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        tools: Optional[list] = None,
    ) -> dict:
        """Get a non-streaming chat response, returning raw message dict."""
        prepared_messages = self.prepare_messages_for_api(messages, system_prompt)
        body = {
            "model": self.bot_config.model,
            "messages": prepared_messages,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if self.bot_config.max_tokens:
            body["max_tokens"] = self.bot_config.max_tokens

        try:
            async with httpx.AsyncClient(base_url=self.bot_config.base_url) as client:
                response = await client.post(
                    self.bot_config.custom_api_path if self.bot_config.custom_api_path else "/chat/completions",
                    headers={
                        "HTTP-Referer": "https://luohy15.com",
                        "X-Title": "y-agent",
                        "Authorization": f"Bearer {self.bot_config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                if "choices" not in data or not data["choices"]:
                    error_msg = data.get("error", {}).get("message", "") if isinstance(data.get("error"), dict) else str(data.get("error", ""))
                    raise Exception(f"API returned no choices: {error_msg or data}")
                msg = data["choices"][0]["message"]
                return {
                    "content": msg.get("content"),
                    "tool_calls": msg.get("tool_calls"),
                    "provider": data.get("provider", self.bot_config.name),
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
            if isinstance(e, ClientError):
                raise
            raise Exception(f"Error getting chat response: {str(e)}")
