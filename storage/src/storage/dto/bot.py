from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

DEFAULT_OPENROUTER_CONFIG = {
    "provider": {
        "sort": "throughput"
    }
}

@dataclass
class BotConfig:
    name: str
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    api_type: Optional[str] = None
    model: str = ""
    description: Optional[str] = None
    openrouter_config: Optional[Dict] = None
    prompts: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    custom_api_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'BotConfig':
        return cls(**data)

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
