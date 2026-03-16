import csv
import html
import io
import json
import os
import re
from hashlib import md5
from typing import List

import tiktoken

from app.definitions import COMPLETION_MODEL

tiktoken_encoders = {}


def read_file(file_path):
    with open(file_path, "r") as f:
        return f.read()


def get_docs(root_dir):
    text_files = []
    for path, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.lower().endswith(('.txt', '.md', '.mdx', '.yaml', '.yml', '.tex', '.rst')):
                text_files.append(os.path.join(path, filename))
    return text_files


def make_hash(text, prefix=""):
    return prefix + md5(text.encode()).hexdigest()


# Refer the utils functions of the official GraphRAG implementation:
# https://github.com/microsoft/graphrag
def clean_str(text: str) -> str:
    """Clean an input string by removing HTML escapes, control characters, and other unwanted characters."""
    assert isinstance(text, str)

    result = html.unescape(text.strip())
    # https://stackoverflow.com/questions/4324790/removing-control-characters-from-a-string-in-python
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", result)


def split_string_by_multi_markers(content: str, markers: list[str]) -> list[str]:
    """Split a string by multiple markers."""
    if not markers:
        return [content]
    results = re.split("|".join(re.escape(marker) for marker in markers), content)
    return [r.strip() for r in results if r.strip()]


def extract_json_from_text(content: str):
    json_str = re.search(r"{.*}", content, re.DOTALL)
    if json_str is not None:
        json_str = json_str.group(0)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None
    return None


def truncate_list_by_token_size(data_list, get_text_for_row, max_token_size=4000, model=COMPLETION_MODEL):
    if max_token_size <= 0:
        return []
    tokens = 0
    for i, data in enumerate(data_list):
        tokens += len(get_encoded_tokens(get_text_for_row(data), model))
        if tokens >= max_token_size:
            return data_list[:i]

    return data_list


def get_encoded_tokens(text, model=COMPLETION_MODEL):
    global tiktoken_encoders
    if not model in tiktoken_encoders:
        try:
            tiktoken_encoders[model] = tiktoken.encoding_for_model(model)
        except KeyError:
            # Keep compatibility with newer model ids not yet known by local tiktoken.
            tiktoken_encoders[model] = tiktoken.get_encoding("o200k_base")

    return tiktoken_encoders[model].encode(text)


def list_of_list_to_csv(data: List[List[str]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(data)
    return output.getvalue()


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
