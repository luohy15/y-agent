import re


def chunks(text):
    labels = {"vega-lite": "[chart]", "mermaid": "[diagram]", "artifact-svg": "[svg]"}
    text = re.sub(r"(?ms)^```(vega-lite|mermaid|artifact-svg)[ \t]*\n.*?(?:^```[ \t]*$|\Z)",
                  lambda match: labels[match[1]], text)
    text = re.sub(r"(?m)^```[^\n]*\n?", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^#{1,6} +", "", text)
    text = re.sub(r"(\*\*|__|`)(.+?)\1", r"\2", text).strip()
    if len(text) <= 1500:
        return [text] if text else []
    parts = [text[start:start+1480] for start in range(0, len(text), 1480)]
    return [f"({index}/{len(parts)}) {part}" for index, part in enumerate(parts, 1)]
