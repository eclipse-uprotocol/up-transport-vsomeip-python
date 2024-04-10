from dataclasses import dataclass
from typing import List


class VsomeipHelper:
    """
    Vsomeip Helper class
    """
    @dataclass
    class UEntityInfo:
        """

        """
        Name: str
        Id: int
        Events: List[int]
        Port: int
        MajorVersion: int

    def services_info(self) -> List[UEntityInfo]:
        return []
