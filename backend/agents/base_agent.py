"""Base class for all process agents."""
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class AgentResult:
    agent_name: str
    status: str          # done | warning | skipped | error
    records_checked: int = 0
    exceptions: List[Dict] = field(default_factory=list)
    journal_entries: int = 0
    summary: str = ""
