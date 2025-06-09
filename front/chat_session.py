from dataclasses import dataclass, field
from uuid import uuid4
from typing import List, Dict, Optional, Literal

UPDATE_DIVE_INFORMATION_TOOL = None
GET_GPT_TOOL = None

MessageRole = Literal["user", "assistant", "tool"]

@dataclass
class ChatSession:
    """Manages a chat session with message history and dive integration."""

    id: str = field(default_factory=lambda: str(uuid4()))
    messages: List[Dict] = field(default_factory=list)

    dive_session_id: Optional[str] = None
    current_dive: dict = field(default_factory=dict)
    metadata_done: bool = False

    available_tools: List[dict] = field(default_factory=list)

    def add(self, role: MessageRole, text: str) -> None:
        """Add a message to the chat session with validation.
        
        Args:
            role: The role of the message sender ('user', 'assistant', or 'system')
            text: The message content
            
        Raises:
            ValueError: If role is invalid or text is empty
        """
        if role not in ["user", "assistant", "tool"]:
            raise ValueError(f"Invalid role '{role}'. Must be one of the following: user, assistant, tool")
        
        if not text or not isinstance(text, str):
            raise ValueError("Message text must be a string")

        self.messages.append({"role": role, "content": text})

    def next_tools(self) -> List:
        """ Return only the tools Claude may see right now."""
        if self.dive_session_id is None: #no video yet
            return []
        #metadata_done = all(self.current_dive.get(field) for field in ["dive_date", "dive_number", "dive_location"])
        #return [] if metadata_done else self.available_tools
        return self.available_tools
