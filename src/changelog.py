"""
Reads the change history from CHANGELOG.md for the page "Was ist neu"

Format of the file: a heading "## <version> – <date>" per version (the date is
optional), followed by one line starting with "- " per change. Everything
else is ignored. The text is shown as plain text, apart from `code` spans.
"""
import os
import re

HEADING = re.compile(r'^##\s+(\d+(?:\.\d+)+)(?:\s*[–-]\s*(\S.*?))?\s*$')

_cache = {'mtime': None, 'entries': []}


def load(path):
    """
    Read the change history

    Args:
    path (str): Path of CHANGELOG.md

    Returns:
    list: One dict per version with "version", "date" (may be None) and "changes", newest first as in the file
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    if _cache['mtime'] == mtime:
        return _cache['entries']
    entries = []
    with open(path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.rstrip('\n')
            heading = HEADING.match(line)
            if heading:
                entries.append({'version': heading.group(1), 'date': heading.group(2), 'changes': []})
            elif line.startswith('- ') and entries:
                entries[-1]['changes'].append(line[2:].strip())
    _cache.update(mtime=mtime, entries=entries)
    return entries


def split_code(text):
    """
    Split a change into plain text and `code` spans for the template

    Returns:
    list: Tuples (is_code, text)
    """
    parts = []
    for index, part in enumerate(text.split('`')):
        if part:
            parts.append((index % 2 == 1, part))
    return parts
