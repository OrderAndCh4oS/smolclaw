import pytest

from app.obsidian import parse_wiki_links, parse_tags, parse_frontmatter


class TestParseWikiLinks:
    def test_parse_wiki_links_simple(self):
        result = parse_wiki_links("see [[Python]]")
        assert result == [("Python", "Python")]

    def test_parse_wiki_links_aliased(self):
        result = parse_wiki_links("see [[Python|py]]")
        assert result == [("Python", "py")]

    def test_parse_wiki_links_multiple(self):
        result = parse_wiki_links("[[Python]] and [[JavaScript|JS]]")
        assert len(result) == 2
        assert result[0] == ("Python", "Python")
        assert result[1] == ("JavaScript", "JS")

    def test_parse_wiki_links_none(self):
        result = parse_wiki_links("no links here")
        assert result == []


class TestParseTags:
    def test_parse_tags(self):
        result = parse_tags("#python #web")
        assert result == ["python", "web"]

    def test_parse_tags_ignores_code_blocks(self):
        content = "outside #real\n```\n#fake\n```"
        result = parse_tags(content)
        assert "real" in result
        assert "fake" not in result

    def test_parse_tags_ignores_headings(self):
        content = "# Heading\nsome text #tag"
        result = parse_tags(content)
        assert "tag" in result
        assert "Heading" not in result


class TestParseFrontmatter:
    def test_parse_frontmatter(self):
        content = "---\ntitle: Test\nauthor: Me\n---\nBody text"
        result = parse_frontmatter(content)
        assert result == {"title": "Test", "author": "Me"}

    def test_parse_frontmatter_missing(self):
        result = parse_frontmatter("No frontmatter here")
        assert result == {}

    def test_parse_frontmatter_with_types(self):
        content = "---\ntags:\n  - python\n  - web\ncount: 42\nnested:\n  key: value\n---\nBody"
        result = parse_frontmatter(content)
        assert result["tags"] == ["python", "web"]
        assert result["count"] == 42
        assert result["nested"] == {"key": "value"}
