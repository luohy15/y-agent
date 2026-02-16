import os
from dataclasses import dataclass
from typing import List, Optional

from loguru import logger

from storage.entity.dto import VmConfig


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


def _parse_skill_from_content(skill_file: str, content: str) -> SkillMeta:
    """Parse a SkillMeta from a skill file path and its content."""
    # entry name is the parent directory name
    entry = os.path.basename(os.path.dirname(skill_file))
    meta = _parse_frontmatter(content)
    name = meta.get("name", entry)
    description = meta.get("description", "")
    return SkillMeta(name=name, description=description, location=skill_file)


def _discover_skills_in_dir(skills_dir: str) -> List[SkillMeta]:
    """Discover skills from a single skills directory (local only)."""
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
            skills.append(_parse_skill_from_content(
                os.path.abspath(skill_file), content,
            ))
        except Exception as e:
            logger.warning(f"Failed to load skill from {skill_file}: {e}")

    return skills


_FIND_SKILLS_SCRIPT = r"""
for dir in {dirs}; do
  [ -d "$dir" ] || continue
  find -L "$dir" -maxdepth 2 \( -name "SKILL.md" -o -name "skill.md" \) -print0 | while IFS= read -r -d '' f; do
    printf '===SKILL_FILE:%s===\n' "$f"
    cat "$f"
  done
done
"""


async def _discover_skills_remote(search_dirs: List[str], vm_config: VmConfig) -> List[SkillMeta]:
    """Discover skills from remote VM with a single request."""
    from agent.tools.sprites_exec import sprites_exec

    dirs_str = " ".join(f'"{d}"' for d in search_dirs)
    script = _FIND_SKILLS_SCRIPT.format(dirs=dirs_str)

    try:
        output = await sprites_exec(vm_config, ["bash", "-c", script])
    except Exception as e:
        logger.warning(f"Failed to discover remote skills: {e}")
        return []

    if not output or not output.strip():
        return []

    # Parse output: ===SKILL_FILE:<path>=== followed by file content
    skills = []
    parts = output.split("===SKILL_FILE:")
    for part in parts[1:]:  # skip empty first element
        sep_idx = part.find("===\n")
        if sep_idx == -1:
            continue
        skill_file = part[:sep_idx]
        content = part[sep_idx + 4:]  # skip "===\n"
        try:
            skills.append(_parse_skill_from_content(skill_file, content))
        except Exception as e:
            logger.warning(f"Failed to parse remote skill {skill_file}: {e}")

    return skills


async def discover_skills(skills_dir: Optional[str] = None, vm_config: Optional[VmConfig] = None) -> List[SkillMeta]:
    """Discover skills from multiple directories.

    Search order (later entries override earlier ones by name):
    1. ~/.agents/skills (home directory)
    2. .agents/skills (project directory, i.e. cwd)

    When vm_config is provided, uses a single remote command to discover all skills.
    """
    if skills_dir is not None and (not vm_config or not vm_config.api_token):
        return _discover_skills_in_dir(skills_dir)

    search_dirs = [skills_dir] if skills_dir is not None else [
        "~/.agents/skills",
        ".agents/skills",
    ]

    if vm_config and vm_config.api_token:
        all_skills = await _discover_skills_remote(search_dirs, vm_config)
    else:
        # Local: expand paths and discover
        expanded = [
            os.path.expanduser(d) if d.startswith("~") else os.path.join(os.getcwd(), d) if not os.path.isabs(d) else d
            for d in search_dirs
        ]
        all_skills = []
        for d in expanded:
            all_skills.extend(_discover_skills_in_dir(d))

    seen = {}
    for skill in all_skills:
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
