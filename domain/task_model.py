"""Task domain models for the scheduling system.

This module defines the structures required to represent tasks, their specific
requirements, and the flexible options available to fulfill them.

Refactored to support a Unified Quantified Skill System, replacing the previous
Enum-based structure with a flexible name-to-level mapping.
"""

import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class Requirement:
    """Defines a specific demand for a group of workers with certain attributes.

    A requirement specifies that the system needs 'count' number of workers
    who possess ALL the listed skills at or above the specified levels.

    Attributes:
        count (int): The number of workers required for this specific profile.
        required_skills (Dict[str, int]): A dictionary mapping skill names to
            the minimum level required (e.g., {"Cook": 5, "English": 3}).
            If empty, implies any worker is suitable (unskilled).
    """
    count: int
    required_skills: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        """Validates count and normalizes skill keys to Title Case.

        Skill names are normalized to match the convention used by
        ``Worker.set_skill_level()`` (e.g., "cook" → "Cook"), ensuring
        case-insensitive matching across all code paths (API, Excel, solver).
        """
        if self.count < 1:
            raise ValueError(f"Requirement count must be >= 1, got {self.count}")
        # Normalize skill keys to Title Case for case-insensitive matching
        if self.required_skills:
            self.required_skills = {
                k.strip().title(): v for k, v in self.required_skills.items()
            }

    def __repr__(self) -> str:
        """Returns a string representation of the requirement."""
        if not self.required_skills:
            skills_str = "Any Skill"
        else:
            skills_str = ", ".join(
                [f"{name}:{level}" for name, level in self.required_skills.items()]
            )
        return f"Requirement(Count={self.count}, Skills=[{skills_str}])"


@dataclass
class TaskOption:
    """Represents one valid configuration to fulfill a task.

    A task might be solvable in multiple ways (e.g., "1 Senior Chef" OR
    "2 Junior Cooks"). Each 'way' is a TaskOption.

    Attributes:
        requirements (List[Requirement]): A list of requirements that must be met
            simultaneously for this option to be valid.
        preference_score (int): A score indicating how desirable this option is.
            Higher scores represent higher preference. Default is 0.
        priority (int): Manager-assigned priority ranking (1=most preferred,
            5=least preferred). Used by TaskOptionPriorityConstraint to apply
            soft penalties for lower-priority selections. Default is 1.
    """
    requirements: List[Requirement] = field(default_factory=list)
    preference_score: int = 0
    priority: int = 1

    def __post_init__(self) -> None:
        """Validates that priority is within range 1-5."""
        if not 1 <= self.priority <= 5:
            raise ValueError(f"TaskOption priority must be 1-5, got {self.priority}")

    def add_requirement(self, count: int, required_skills: Optional[Dict[str, int]] = None) -> None:
        """Adds a specific requirement to this option configuration.

        Args:
            count: The number of workers needed.
            required_skills: A dictionary mapping skill names to minimum levels.
                Defaults to an empty dictionary if None.
        """
        skills = required_skills if required_skills else {}
        self.requirements.append(Requirement(count=count, required_skills=skills))

    def __repr__(self) -> str:
        return f"TaskOption(Score={self.preference_score}, Priority={self.priority}, Requirements={self.requirements})"


@dataclass
class Task:
    """Represents a specific job or assignment within a shift.

    A Task acts as a container for multiple TaskOptions. The optimization solver
    must select exactly one TaskOption to fulfill the task.

    Attributes:
        task_id (str): A unique identifier for the task.
        name (str): The human-readable name of the task.
        options (List[TaskOption]): A list of valid ways to staff this task.
    """
    name: str
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    options: List[TaskOption] = field(default_factory=list)

    def add_option(self, option: TaskOption) -> None:
        """Adds a valid staffing option to the task.

        Args:
            option: A configured TaskOption instance.
        """
        self.options.append(option)

    def __repr__(self) -> str:
        return f"Task(Name='{self.name}', ID={self.task_id}, Options Count={len(self.options)})"