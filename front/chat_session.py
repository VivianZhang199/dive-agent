from dataclasses import dataclass, field
from uuid import uuid4
from typing import List, Dict

UPDATE_METADATA_TOOL = None
GET_GPT_TOOL = None

@dataclass
class ChatSession:
    
    id: str = field(default_factory=lambda: str(uuid4()))
    messages: List[Dict] = field(default_factory=list)

    dive_session_id: str | None = None
    current_dive: dict = field(default_factory=dict)
    metadata_done: bool = False

    def add(self, role: str, text: str) -> None:
        self.messages.append({"role": role, "content": text})

    def next_tools(self):
        """ Return only the tools Claude may see right now."""
        if self.dive_session_id is None: #no video yet
            return []
        if not self.metadata_done:
            return [UPDATE_METADATA_TOOL]
        return [UPDATE_METADATA_TOOL]
