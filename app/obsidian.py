import re
from typing import List, Tuple


def parse_wiki_links(content: str) -> List[Tuple[str, str]]:
    """Parse [[target]] and [[target|alias]] wiki links. Returns list of (target, display_text) tuples."""
    pattern = re.compile(r'\[\[([^\]]+?)(?:\|([^\]]+?))?\]\]')
    results = []
    for match in pattern.finditer(content):
        target = match.group(1)
        alias = match.group(2) or target
        results.append((target, alias))
    return results


def parse_tags(content: str) -> List[str]:
    """Parse #tags from content, ignoring tags in code blocks and headings."""
    # Remove code blocks
    no_code = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
    # Match tags: # followed by word chars, but not at start of line (headings)
    tags = re.findall(r'(?:^|(?<=\s))#(\w+)', no_code, flags=re.MULTILINE)
    return tags
