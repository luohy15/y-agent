import os
from dataclasses import dataclass
from typing import List, Optional

from loguru import logger


@dataclass
class SkillMeta:
    name: str
    description: str
    location: str


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown content."""
    import yaml

    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse YAML frontmatter: {e}")
        return {}


def _discover_skills_in_dir(skills_dir: str) -> List[SkillMeta]:
    """Discover skills from a single skills directory."""
    if not os.path.isdir(skills_dir):
        return []

    skills = []
    for entry in sorted(os.listdir(skills_dir)):
        subdir = os.path.join(skills_dir, entry)
        if not os.path.isdir(subdir):
            continue

        # Look for SKILL.md or skill.md
        skill_file = None
        for name in ("SKILL.md", "skill.md"):
            candidate = os.path.join(subdir, name)
            if os.path.isfile(candidate):
                skill_file = candidate
                break

        if not skill_file:
            continue

        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()
            meta = _parse_frontmatter(content)
            name = meta.get("name", entry)
            description = meta.get("description", "")
            skills.append(SkillMeta(
                name=name,
                description=description,
                location=os.path.abspath(skill_file),
            ))
        except Exception as e:
            logger.warning(f"Failed to load skill from {skill_file}: {e}")

    return skills


def discover_skills(skills_dir: Optional[str] = None) -> List[SkillMeta]:
    """Discover skills from multiple directories.

    Search order (later entries override earlier ones by name):
    1. ~/.agents/skills (home directory)
    2. .agents/skills (project directory, i.e. cwd)
    """
    if skills_dir is not None:
        return _discover_skills_in_dir(skills_dir)

    search_dirs = [
        os.path.expanduser("~/.agents/skills"),
        os.path.join(os.getcwd(), ".agents", "skills"),
    ]

    seen = {}
    for d in search_dirs:
        for skill in _discover_skills_in_dir(d):
            seen[skill.name] = skill

    return sorted(seen.values(), key=lambda s: s.name)


def skills_to_prompt(skills: List[SkillMeta]) -> str:
    """Generate an <available_skills> XML block for the system prompt."""
    if not skills:
        return ""

    lines = ["<available_skills>"]
    for skill in skills:
        lines.append("  <skill>")
        lines.append(f"    <name>{skill.name}</name>")
        lines.append(f"    <description>{skill.description}</description>")
        lines.append(f"    <location>{skill.location}</location>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)
