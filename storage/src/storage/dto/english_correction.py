from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class EnglishCorrection:
    correction_id: str
    chat_id: str
    message_id: str
    message_at: str
    message_at_unix: int
    original_text: str
    corrected_text: str
    error_categories: List[str]
    explanation: str
    dismissed: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_at_unix: Optional[int] = None
    updated_at_unix: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "EnglishCorrection":
        cats = data.get("error_categories") or []
        if not isinstance(cats, list):
            cats = list(cats)
        return cls(
            correction_id=data["correction_id"],
            chat_id=data["chat_id"],
            message_id=data["message_id"],
            message_at=data["message_at"],
            message_at_unix=int(data["message_at_unix"]),
            original_text=data["original_text"],
            corrected_text=data["corrected_text"],
            error_categories=[str(c) for c in cats],
            explanation=data["explanation"],
            dismissed=bool(data.get("dismissed", False)),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            created_at_unix=data.get("created_at_unix"),
            updated_at_unix=data.get("updated_at_unix"),
        )

    def to_dict(self) -> Dict:
        result = {
            "correction_id": self.correction_id,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "message_at": self.message_at,
            "message_at_unix": self.message_at_unix,
            "original_text": self.original_text,
            "corrected_text": self.corrected_text,
            "error_categories": list(self.error_categories or []),
            "explanation": self.explanation,
            "dismissed": self.dismissed,
        }
        if self.created_at is not None:
            result["created_at"] = self.created_at
        if self.updated_at is not None:
            result["updated_at"] = self.updated_at
        if self.created_at_unix is not None:
            result["created_at_unix"] = self.created_at_unix
        if self.updated_at_unix is not None:
            result["updated_at_unix"] = self.updated_at_unix
        return result
