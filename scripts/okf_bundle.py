"""Read-only, deterministic OKF v0.2 migration helpers.

``root`` is the knowledge bundle directory, not the project directory.
All functions return strings/diagnostics and never write files. Caller-provided
source paths and URI/status metadata are retained, not verified or repaired.
Validation diagnostics use ``error:`` for structure, ``warning:`` for broken
links, and ``safety:`` for local-resource risks (not conformance rejection).
Unknown producer keys/types survive. YAML comments/style are not round-tripped.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

from datetime import date, datetime
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote, unquote, urlsplit

import yaml

__all__ = ['parse_markdown', 'render_markdown', 'normalize_concept',
           'rewrite_wikilinks', 'normalize_index', 'normalize_log',
           'validate_markdown']
_RESERVED = {'index.md', 'log.md'}
_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$')
_WIKI = re.compile(r'\[\[([^\[\]\n]+)\]\]')
_DATE_HEADING = re.compile(r'^##\s+(?:\[(\d{4}-\d{2}-\d{2})\]|(\d{4}-\d{2}-\d{2}))(.*?)(?:\r?\n)?$')


class _TextTimestampLoader(yaml.SafeLoader):
    """SafeLoader with timestamp scalars kept as their original text."""


_TextTimestampLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in values
          if tag != 'tag:yaml.org,2002:timestamp']
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_TextTimestampLoader.add_constructor('tag:yaml.org,2002:timestamp',
                                    lambda loader, node: loader.construct_scalar(node))


def _mapping(loader, node, deep=False):
    # Duplicate keys silently discard facts; reject them rather than repair.
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise ValueError(f'duplicate YAML key: {key!r}')
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as exc:
            raise ValueError('unhashable YAML mapping key') from exc
    return result


_TextTimestampLoader.add_constructor('tag:yaml.org,2002:map', _mapping)


def _has_frontmatter(text: str) -> bool:
    return bool(re.match(r'\A(?:\ufeff)?---[ \t]*(?:\r?\n|$)', text))


def parse_markdown(text: str) -> tuple[dict, str]:
    """Parse a top-level mapping, preserving the exact post-delimiter body.

    A missing frontmatter is represented by ``({}, text)`` so plain legacy
    documents can be normalized. Present but empty/nonmapping/unsafe YAML and
    unterminated frontmatter raise ValueError. Unknown extension *keys* are
    supported; unknown YAML constructors are deliberately not executed.
    """
    if not isinstance(text, str):
        raise TypeError('markdown text must be a string')
    if not _has_frontmatter(text):
        return {}, text
    opening = re.match(r'\A(?:\ufeff)?---[ \t]*(?:\r?\n|$)', text)
    closing = re.search(r'^---[ \t]*(?:\r?\n|$)', text[opening.end():], re.MULTILINE)
    if closing is None:
        raise ValueError('unterminated YAML frontmatter')
    end = opening.end()
    try:
        metadata = yaml.load(text[end:end + closing.start()], Loader=_TextTimestampLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError(f'unsafe or invalid YAML frontmatter: {exc}') from exc
    if not isinstance(metadata, dict):
        raise ValueError('YAML frontmatter must be a mapping')
    return metadata, text[end + closing.end():]


def render_markdown(metadata: dict, body: str) -> str:
    """Render safe YAML without changing any body bytes or metadata values."""
    if not isinstance(metadata, dict) or not isinstance(body, str):
        raise TypeError('metadata must be a dict and body a string')
    if not metadata:
        return body
    front = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False,
                           default_flow_style=False, width=1000)
    return '---\n' + front + '---\n' + body


def _timestamp(value) -> bool:
    if not isinstance(value, str) or not _ISO.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.utcoffset() is not None
    except ValueError:
        return False


def _existing(root: Path, value: str) -> str | None:
    """Return a bundle-relative existing file; never follow escaping symlinks."""
    root = Path(root).resolve()
    path = root / value.lstrip('/')
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(root)
        if path.is_file():
            return relative.as_posix()
    except (ValueError, OSError, RuntimeError):
        pass
    return None


def _resolve(root: Path, relative_path: str, target: str) -> str | None:
    target = unquote(target.split('#', 1)[0])
    if not target:
        return '/' + relative_path.lstrip('/') if _existing(root, relative_path) else None
    if urlsplit(target).scheme:
        return None
    forms = [target]
    if not PurePosixPath(target).suffix:
        forms.extend(target + suffix for suffix in ('.md', '.MD', '.Md', '.mD'))
    if target.startswith(('./', '../')):
        for form in forms:
            actual = _existing(root, (PurePosixPath(relative_path).parent / form).as_posix())
            if actual is not None:
                return '/' + actual
        return None
    # Explicit root paths precede document-relative paths and basename guesses.
    for form in forms:
        actual = _existing(root, form)
        if actual is not None:
            return '/' + actual
    if not target.startswith('/'):
        for form in forms:
            actual = _existing(root, (PurePosixPath(relative_path).parent / form).as_posix())
            if actual is not None:
                return '/' + actual
    if '/' not in target and not target.startswith('.'):
        candidates = []
        for p in Path(root).rglob('*'):
            if p.is_file() and p.name.lower().endswith('.md') and p.name in forms:
                actual = _existing(root, p.relative_to(root).as_posix())
                if actual is not None:
                    candidates.append(actual)
        if len(set(candidates)) == 1:
            return '/' + candidates[0]
    return None


def _continue_containers(line: str, containers: tuple):
    """Strip only the active ordered quote/list prefix for lexical matching.

    List widths include marker padding and preceding indentation. Blank list
    lines may continue an item; quotes require their explicit `>` prefix.
    Expanded tabs affect matching columns only, never returned source bytes.
    """
    content, matched = line.expandtabs(4), []
    for kind, width in containers:
        if kind == 'quote':
            prefix = re.match(r'^ {0,3}> ?', content)
            if prefix is None:
                break
            content = content[prefix.end():]
        elif content.strip():
            if not content.startswith(' ' * width):
                break
            content = content[width:]
        matched.append((kind, width))
    return content, tuple(matched)


def _open_containers(content: str, containers: tuple):
    """Recognize composed prefixes in order, including list -> quote."""
    frames = list(containers)
    while True:
        quote_prefix = re.match(r'^ {0,3}> ?', content)
        list_prefix = re.match(r'^ {0,3}(?:[-+*]|\d{1,9}[.)])( +)', content)
        if quote_prefix:
            frames.append(('quote', 0))
            content = content[quote_prefix.end():]
        elif list_prefix:
            # Common Markdown list padding is 1..4 columns; a larger gap
            # contributes one padding column and leaves indented code.
            width = list_prefix.end()
            if len(list_prefix[1]) > 4:
                width -= len(list_prefix[1]) - 1
            frames.append(('list', width))
            content = content[width:]
        else:
            return content, tuple(frames)


def _block_code_lines(body: str):
    """Yield fenced/indented flags without interpreting prose as code."""
    containers, fence = (), None
    for line in body.splitlines(keepends=True):
        content, matched = _continue_containers(line, containers)
        if fence is not None:
            if matched == containers:
                yield True, line
                closing = re.match(r'^ {0,3}(`{3,}|~{3,})([^\r\n]*)', content)
                if (closing and closing[1][0] == fence[0]
                        and len(closing[1]) >= fence[1] and not closing[2].strip()):
                    fence = None
                continue
            # A code fence ends at its container's EOF too. Reprocess this
            # same line outside the ended container; it may be a real edge.
            fence = None
        content, containers = _open_containers(content, matched)
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})([^\r\n]*)', content)
        if marker and not (marker[1][0] == '`' and '`' in marker[2]):
            fence = (marker[1][0], len(marker[1]))
            yield True, line
        elif content.startswith('    '):
            yield True, line
        else:
            yield False, line


def _code_free_segments(body: str):
    """Yield (protected, text), retaining exact original delimiters/bytes.

    This is a conservative lexer, not a CommonMark renderer. Block protection
    runs first so backticks in fences cannot create inline spans outside them.
    Inline spans may cross prose newlines; quoted examples stay on one line.
    """
    token = re.compile(r"(?<!`)(`+)(?!`)(.*?)(?<!`)\1(?!`)|([\"'])[^\r\n]*?\[\[[^\r\n]*?\]\][^\r\n]*?\3", re.DOTALL)

    def prose_segments(text):
        start = 0
        for match in token.finditer(text):
            yield False, text[start:match.start()]
            yield True, match[0]
            start = match.end()
        yield False, text[start:]

    prose = []
    for protected, line in _block_code_lines(body):
        if protected:
            if prose:
                yield from prose_segments(''.join(prose))
                prose.clear()
            yield True, line
        else:
            prose.append(line)
    if prose:
        yield from prose_segments(''.join(prose))


def _lines_with_code_flags(body: str):
    ranges, offset = [], 0
    for protected, part in _code_free_segments(body):
        if protected and part:
            ranges.append((offset, offset + len(part)))
        offset += len(part)
    offset, cursor = 0, 0
    for line in body.splitlines(keepends=True):
        while cursor < len(ranges) and ranges[cursor][1] <= offset:
            cursor += 1
        protected = cursor < len(ranges) and ranges[cursor][0] <= offset < ranges[cursor][1]
        yield protected, line
        offset += len(line)


def rewrite_wikilinks(root: Path, relative_path: str, body: str) -> str:
    """Rewrite graph edges, leaving code literals and surrounding prose intact.

    Unresolved identifiers keep their exact spelling in the destination; no
    `.md` path is invented. Validator emits a nonblocking broken-link warning.
    """
    def replace(match):
        raw = match[1]
        target, separator, alias = raw.partition('|')
        path, fragment_sep, fragment = target.partition('#')
        resolved = _resolve(Path(root), relative_path, path)
        destination = resolved or (path if urlsplit(path).scheme else
                                   '/' + path.lstrip('/') if path else '')
        if fragment_sep:
            destination += '#' + fragment
        label = alias if separator else target
        label = label.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
        destination = quote(destination, safe='/:#?@-._~!$&\'*,;=%')
        return f'[{label}]({destination})'
    return ''.join(part if protected else _WIKI.sub(replace, part)
                   for protected, part in _code_free_segments(body))


def _source(root, relative_path, entry, lookup):
    if isinstance(entry, str):
        result = {'id': entry}
    elif isinstance(entry, dict):
        result = dict(entry)
    else:
        return entry  # Invalid structure is reported, not silently destroyed.
    if isinstance(result.get('resource'), str) and result['resource'].strip():
        return result
    identity = result.get('id', result.get('source_id'))
    original = lookup.get(identity) if isinstance(identity, str) else None
    if isinstance(original, str):
        result['resource'] = original
        return result
    if isinstance(original, dict):
        # Credibility/status values are copied only if actually supplied.
        for key, value in original.items():
            result.setdefault(key, value)
        for key in ('resource', 'source_path', 'uri', 'path', 'project_relative_path'):
            value = original.get(key)
            if isinstance(value, str) and value.strip():
                result['resource'] = value
                return result
    if isinstance(identity, str):
        if urlsplit(identity).scheme in {'https', 'http', 'file'}:
            result['resource'] = identity
            return result
        resolved = _resolve(Path(root), relative_path, identity)
        if resolved:
            result['resource'] = resolved
            return result
    result['resource'] = f'Unresolved original source_id:{identity if identity is not None else "(absent)"}'
    result['resolution'] = 'unresolved'
    return result


def _display(body: str, relative_path: str) -> tuple[str, str]:
    prose = ''.join(part for protected, part in _code_free_segments(body) if not protected)
    heading = re.search(r'^#\s+(.+?)\s*#*\s*$', prose, re.MULTILINE)
    title = heading[1] if heading else PurePosixPath(relative_path).stem
    # A directory preview must not spread private prose into producer metadata.
    # Explicit existing descriptions remain authoritative via setdefault below.
    description = f'Knowledge document: {relative_path}'
    return title, description


def normalize_concept(root: Path, relative_path: str, text: str,
                      source_lookup: dict | None = None, now: str | None = None) -> str:
    """Add minimal concept metadata without upgrading trust or authority."""
    if PurePosixPath(relative_path).name in _RESERVED:
        raise ValueError('reserved index.md/log.md is not a concept')
    metadata, body = parse_markdown(text)
    title, description = _display(body, relative_path)
    if not isinstance(metadata.get('type'), str) or not metadata['type'].strip():
        if 'type' in metadata:
            if 'legacy_type' in metadata and metadata['legacy_type'] != metadata['type']:
                raise ValueError('legacy_type conflict; refusing to lose original type')
            metadata['legacy_type'] = metadata['type']
        metadata['type'] = 'Reference'
    metadata.setdefault('title', title)
    metadata.setdefault('description', description)
    if isinstance(metadata.get('sources'), list):
        metadata['sources'] = [_source(root, relative_path, e, source_lookup or {})
                               for e in metadata['sources']]
    status = metadata.get('status')
    if status is not None and status not in ('draft', 'stable', 'deprecated'):
        if 'workflow_status' in metadata and metadata['workflow_status'] != status:
            if 'legacy_status' in metadata and metadata['legacy_status'] != status:
                raise ValueError('workflow/legacy_status conflict; refusing to lose original status')
            metadata.setdefault('legacy_status', status)
        else:
            metadata.setdefault('workflow_status', status)
        del metadata['status']  # Absent knowledge lifecycle has OKF stable default.
    if 'generated' not in metadata and _timestamp(now):
        metadata['generated'] = {'by': 'process:wiki-desk-okf-migration', 'at': now}
    return render_markdown(metadata, rewrite_wikilinks(root, relative_path, body))


def normalize_index(root: Path, relative_path: str, text: str) -> str:
    """Normalize the reserved index without altering historical counts/prose.

    Existing illegal index metadata is rejected, never silently dropped.
    """
    if PurePosixPath(relative_path).name != 'index.md':
        raise ValueError('normalize_index requires reserved index.md')
    metadata, body = parse_markdown(text)
    if PurePosixPath(relative_path).as_posix() == 'index.md':
        if set(metadata) - {'okf_version'}:
            raise ValueError('bundle-root index permits only okf_version frontmatter')
        metadata.setdefault('okf_version', '0.2')
    elif metadata:
        raise ValueError('nested index must not have frontmatter')
    return render_markdown(metadata, rewrite_wikilinks(root, relative_path, body))


def normalize_log(text: str) -> str:
    """Group dates newest-first; preserve every action/subject/revision.

    Legacy `## [date] action | subject` becomes a date group with the exact
    action/subject retained as a bullet. Entries sharing a date are appended,
    not keyed by action or deduplicated. Undated sections remain unchanged.
    """
    metadata, body = parse_markdown(text)
    if metadata:
        raise ValueError('log.md must not have frontmatter')
    prefix, groups, current = [], {}, None
    for protected, line in _lines_with_code_flags(body):
        match = None if protected else _DATE_HEADING.match(line)
        if match:
            stamp = match[1] or match[2]
            try:
                date.fromisoformat(stamp)
            except ValueError as exc:
                raise ValueError(f'invalid log date: {stamp}') from exc
            current = stamp
            groups.setdefault(stamp, [])
            tail = match[3].strip()
            if tail:
                groups[stamp].append('\n- ' + tail + '\n')
        elif current is None:
            prefix.append(line)
        else:
            groups[current].append(line)
    if not groups:
        return body
    result = ''.join(prefix).rstrip('\r\n') + '\n\n'
    for stamp in sorted(groups, reverse=True):
        content = ''.join(groups[stamp]).strip('\r\n')
        result += '## ' + stamp + '\n\n' + content + '\n\n'
    return result.rstrip('\n') + '\n'


def validate_markdown(root: Path, relative_path: str, text: str) -> list[str]:
    """Return structural errors and distinct, non-rejecting link/safety notices."""
    issues = []
    try:
        metadata, body = parse_markdown(text)
    except (ValueError, TypeError) as exc:
        return [f'error:frontmatter:{exc}']
    name = PurePosixPath(relative_path).name
    if name == 'index.md':
        is_root = PurePosixPath(relative_path).as_posix() == 'index.md'
        if _has_frontmatter(text) and (not is_root or set(metadata) - {'okf_version'}):
            issues.append('error:index:only root okf_version frontmatter is permitted')
    elif name == 'log.md':
        if _has_frontmatter(text):
            issues.append('error:log:frontmatter is not permitted')
        dates = []
        for protected, line in _lines_with_code_flags(body):
            if protected:
                continue
            line = line.rstrip('\r\n')
            if line.startswith('## '):
                stamp = line[3:]
                try:
                    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp):
                        raise ValueError
                    date.fromisoformat(stamp)
                    dates.append(stamp)
                except ValueError:
                    issues.append(f'error:log:non-ISO date heading:{stamp}')
        if dates != sorted(set(dates), reverse=True):
            issues.append('error:log:date groups must be unique and newest-first')
    else:
        if not _has_frontmatter(text):
            issues.append('error:frontmatter:concept requires YAML frontmatter')
        if not isinstance(metadata.get('type'), str) or not metadata['type'].strip():
            issues.append('error:type:non-empty string required')
    sources = metadata.get('sources', [])
    if not isinstance(sources, list):
        issues.append('error:sources:list of mappings required')
        sources = []
    for i, entry in enumerate(sources):
        if not isinstance(entry, dict):
            issues.append(f'error:sources[{i}]:mapping required')
            continue
        resource = entry.get('resource')
        if not isinstance(resource, str) or not resource.strip():
            issues.append(f'error:sources[{i}].resource:non-empty string required')
        for key in ('last_modified',):
            if key in entry and not _timestamp(entry[key]):
                issues.append(f'error:sources[{i}].{key}:offset ISO timestamp required')
        if isinstance(resource, str):
            parsed = urlsplit(resource)
            if parsed.scheme in {'javascript', 'data'}:
                issues.append(f'safety:sources[{i}]:unsafe URI scheme')
            elif not parsed.scheme and '..' in PurePosixPath(unquote(resource)).parts:
                candidate = Path(root) / PurePosixPath(relative_path).parent / unquote(resource)
                try:
                    candidate.resolve().relative_to(Path(root).resolve())
                except (ValueError, OSError, RuntimeError):
                    issues.append(f'safety:sources[{i}]:local path escapes bundle')
    for family in ('generated', 'verified'):
        if family not in metadata:
            continue
        value = metadata[family]
        events = value if family == 'verified' and isinstance(value, list) else [value]
        for i, event in enumerate(events):
            label = f'{family}[{i}]'
            if not isinstance(event, dict):
                issues.append(f'error:{label}:actor event mapping required')
                continue
            if not isinstance(event.get('by'), str) or not event['by'].strip():
                issues.append(f'error:{label}.by:actor string required')
            if (family == 'verified' or 'at' in event) and not _timestamp(event.get('at')):
                issues.append(f'error:{label}.at:offset ISO timestamp required')
    if 'stale_after' in metadata and not _timestamp(metadata['stale_after']):
        issues.append('error:stale_after:offset ISO timestamp required')
    windows = [('usage_window', metadata.get('usage_window'))]
    windows.extend((f'sources[{i}].usage_window', source.get('usage_window'))
                   for i, source in enumerate(sources) if isinstance(source, dict))
    for label, window in windows:
        if window is None:
            continue
        if not isinstance(window, dict):
            issues.append(f'error:{label}:mapping required')
            continue
        for key in ('from', 'to'):
            if key in window and not _timestamp(window[key]):
                issues.append(f'error:{label}.{key}:offset ISO timestamp required')
    for protected, part in _code_free_segments(body):
        if protected:
            continue
        for match in re.finditer(r'(?<!!)\[[^\]\n]+\]\(([^\s)]*)(?:\s+[^)]*)?\)', part):
            target = unquote(match[1].strip('<>'))
            if not target or target.startswith('#') or urlsplit(target).scheme:
                continue
            path = target.split('#', 1)[0]
            actual = _existing(root, path if path.startswith('/') else
                               (PurePosixPath(relative_path).parent / path).as_posix())
            # Directory indexes may link to subdirectories rather than concepts.
            candidate = Path(root) / (path.lstrip('/') if path.startswith('/') else
                                      (PurePosixPath(relative_path).parent / path).as_posix())
            if actual is None and not candidate.is_dir():
                issues.append(f'warning:broken-link:{target}')
        for match in _WIKI.finditer(part):
            target = match[1].partition('|')[0]
            if _resolve(root, relative_path, target) is None:
                issues.append(f'warning:broken-link:wikilink:{target}')
    return list(dict.fromkeys(issues))
