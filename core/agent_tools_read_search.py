import ast
import json
import os
import re

from core.agent_tools_base import get_project_root, resolve_path


def read_file(cls, path, start_line=1, end_line=150, with_line_numbers=False):
    full_path = resolve_path(path)
    if not os.path.exists(full_path):
        return f"[Error: File not found: {path}]"
    if "crash.log" in os.path.basename(full_path):
        return "[Skipping crash.log to prevent file lock issues]"
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        total_lines = len(lines)
        content = cls._render_line_excerpt(lines, start_line, end_line, with_line_numbers=with_line_numbers)
        if total_lines > end_line:
            content += f"\n[... truncated to lines {start_line}-{end_line} of {total_lines}]"
        return content
    except Exception as e:
        return f"[Error reading file: {e}]"


def list_files(cls, root_dir="."):
    full_root = resolve_path(root_dir)
    if not os.path.exists(full_root):
        return f"[Error: Path not found: {root_dir}]"
    if os.path.isfile(full_root):
        return os.path.basename(full_root)
    output = []
    for root, dirs, files in os.walk(full_root):
        dirs[:] = [d for d in dirs if d not in cls.EXCLUDE_DIRS]
        level = root.replace(full_root, '').count(os.sep)
        indent = ' ' * 2 * level
        output.append(f"{indent}{os.path.basename(root)}/")
        sub_indent = ' ' * 2 * (level + 1)
        for file_name in sorted(files):
            output.append(f"{sub_indent}{file_name}")
        if len(output) > 2000:
            output.append("[... truncated]")
            break
    return "\n".join(output)


def find_files(cls, pattern, root_dir=".", case_insensitive=False, max_results=100):
    import fnmatch
    base_dir = resolve_path(root_dir)
    if not os.path.exists(base_dir):
        return f"[Error: Path not found: {root_dir}]"
    limit = max(1, int(max_results or 100))
    pattern_cmp = pattern.lower() if case_insensitive else pattern
    matches = []
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in cls.EXCLUDE_DIRS]
        for file_name in files:
            candidate = file_name.lower() if case_insensitive else file_name
            if fnmatch.fnmatch(candidate, pattern_cmp):
                matches.append(os.path.relpath(os.path.join(root, file_name), base_dir))
                if len(matches) >= limit:
                    return "\n".join(matches)
    return "\n".join(matches) if matches else "[No files found]"


def search_files(cls, query, root_dir=".", file_pattern=None, case_insensitive=False, context_lines=0, max_results=100):
    import fnmatch
    base_dir = resolve_path(root_dir)
    if not os.path.exists(base_dir):
        return f"[Error: Path not found: {root_dir}]"
    if not str(query or ""):
        return "[Error: search_files query cannot be empty]"
    pattern = re.compile(re.escape(str(query or "")), re.IGNORECASE if case_insensitive else 0)
    hits = []
    limit = max(1, int(max_results or 100))
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in cls.EXCLUDE_DIRS]
        for file_name in files:
            if file_pattern and not fnmatch.fnmatch(file_name, file_pattern):
                continue
            full_path = os.path.join(root, file_name)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception:
                continue
            rel_path = os.path.relpath(full_path, base_dir)
            for idx, line in enumerate(lines, start=1):
                if pattern.search(line):
                    hits.append(cls._format_context_block(rel_path, lines, idx, context_lines=context_lines))
                    if len(hits) >= limit:
                        return "\n\n".join(hits)
    return "\n\n".join(hits) if hits else "[No matches found]"


def read_json(cls, path, query=None, max_chars=4000):
    full_path = resolve_path(path)
    if not os.path.exists(full_path):
        return f"[Error: File not found: {path}]"
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        value = cls._lookup_json_path(data, query) if query else data
        rendered = cls._render_json_value(value) if query else cls._summarize_json(value)
        rendered = str(rendered)
        max_chars = max(200, int(max_chars or 4000))
        if len(rendered) > max_chars:
            rendered = rendered[:max_chars] + f"\n... [{len(rendered) - max_chars} chars truncated]"
        return rendered
    except Exception as e:
        return f"[Error reading JSON: {e}]"


def get_file_structure(cls, path):
    parsed, error = cls._load_python_ast(path)
    if error:
        return error
    _full_path, _source, _lines, tree = parsed
    symbols = cls._collect_python_symbols(tree)
    if not symbols:
        return "[No classes or functions found]"
    output = []
    for symbol in symbols:
        output.append(f"{'  ' * int(symbol['depth'])}{cls._structure_label(symbol['kind'])}: {symbol['name']} (Line {symbol['lineno']})")
    return "\n".join(output)


def find_symbol(cls, symbol, root_dir=".", symbol_type=None, file_pattern="*.py", max_results=50):
    try:
        matches, _base_dir = cls._scan_python_symbols(
            root_dir=root_dir,
            file_pattern=file_pattern,
            predicate=lambda entry: cls._symbol_matches_query(entry, symbol, symbol_type=symbol_type),
            max_results=max_results,
        )
    except Exception as e:
        return f"[Error: {e}]"
    if not matches:
        return f"[No symbol found: {symbol}]"
    return "\n".join(f"{rel_path}:{entry['lineno']}: {entry['kind']} {entry['qualified_name']}" for rel_path, entry in matches)


def find_references(cls, symbol, root_dir=".", file_pattern="*.py", context_lines=1, max_results=50, include_definitions=False):
    try:
        symbol_matches, base_dir = cls._scan_python_symbols(root_dir=root_dir, file_pattern=file_pattern, max_results=1000)
    except Exception as e:
        return f"[Error: {e}]"
    resolved = cls._resolve_symbol_query([entry for _rel_path, entry in symbol_matches], symbol)
    target_names = {symbol, *{entry['name'] for entry in resolved}, *{entry['qualified_name'] for entry in resolved}}
    word_re = re.compile(r'(?<![A-Za-z0-9_])(' + '|'.join(re.escape(name) for name in sorted(target_names)) + r')(?![A-Za-z0-9_])')
    hits = []
    for rel_path, full_path in cls._iter_python_files(base_dir, file_pattern=file_pattern):
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception:
            continue
        definitions = set()
        if not include_definitions:
            try:
                tree = ast.parse(''.join(lines))
                definitions = {int(getattr(node, 'lineno', -1)) for node in ast.walk(tree) if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and getattr(node, 'name', '') in target_names}
            except Exception:
                definitions = set()
        for idx, line in enumerate(lines, start=1):
            if idx in definitions:
                continue
            if word_re.search(line):
                hits.append(cls._format_context_block(rel_path, lines, idx, context_lines=context_lines))
                if len(hits) >= max(1, int(max_results or 50)):
                    return "\n\n".join(hits)
    return "\n\n".join(hits) if hits else f"[No references found: {symbol}]"


def read_python_symbols(cls, path, symbols, with_line_numbers=True, max_symbols=5):
    parsed, error = cls._load_python_ast(path)
    if error:
        return error
    _full_path, _source, lines, tree = parsed
    entries = cls._collect_python_symbols(tree)
    requested = [item.strip() for item in str(symbols or "").split(',') if item.strip()][:max(1, int(max_symbols or 5))]
    if not requested:
        return "[Error: read_python_symbols requires at least one symbol name]"
    output = []
    for query in requested:
        matched = cls._resolve_symbol_query([entry for entry in entries if entry['name'] == query or entry['qualified_name'] == query], query)
        if not matched:
            output.append(f"[Symbol not found: {query}]")
            continue
        for entry in matched:
            excerpt = cls._render_line_excerpt(lines, entry['lineno'], entry['end_lineno'], with_line_numbers=with_line_numbers)
            output.append(f"=== {entry['kind'].title()} {entry['qualified_name']} (lines {entry['lineno']}-{entry['end_lineno']}) ===\n{excerpt}".rstrip())
    return "\n\n".join(output)


def find_tests(cls, query=None, source_path=None, root_dir="tests", max_results=20):
    base_dir = resolve_path(root_dir)
    if not os.path.exists(base_dir):
        return f"[Error: Path not found: {root_dir}]"
    terms = cls._build_test_search_terms(query=query, source_path=source_path)
    ranked = []
    for rel_path, full_path in cls._iter_python_files(base_dir, file_pattern='test*.py'):
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source)
        except Exception:
            continue
        entries = cls._collect_test_entries(tree, source.splitlines())
        entry_names = ' '.join(entry['full_name'].lower() for entry in entries)
        source_lower = source.lower()
        matched_terms = [term for term in terms if term in rel_path.lower() or term in entry_names or term in source_lower]
        if query and not matched_terms:
            continue
        ranked.append((cls._score_test_match(rel_path.lower(), entry_names, source_lower, matched_terms), rel_path, entries))
    if not ranked:
        return "[No tests found]"
    ranked.sort(key=lambda item: (-item[0], item[1]))
    lines = []
    limit = max(1, int(max_results or 20))
    root_display = str(root_dir or ".").replace('\\', '/').strip().strip('/')
    for _score, rel_path, entries in ranked:
        display_path = f"{root_display}/{rel_path.replace('\\', '/')}" if root_display and root_display != "." else rel_path.replace('\\', '/')
        if not entries:
            lines.append(display_path)
        else:
            for entry in entries:
                lines.append(f"{display_path}:{entry['lineno']} | {entry['full_name']}")
                if len(lines) >= limit:
                    return "\n".join(lines)
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def get_imports(cls, path, include_external=True):
    parsed, error = cls._load_python_ast(path)
    if error:
        return error
    _full_path, _source, lines, tree = parsed
    imports = cls._collect_import_statements(tree, lines)
    if not include_external:
        imports = [entry for entry in imports if entry['category'] != 'external']
    if not imports:
        return "[No imports found]"
    return "\n".join(f"{entry['lineno']}: {entry['statement']} [{entry['category']}]" for entry in imports)


def find_importers(cls, target, root_dir=".", file_pattern="*.py", max_results=50):
    base_dir = resolve_path(root_dir)
    if not os.path.exists(base_dir):
        return f"[Error: Path not found: {root_dir}]"
    candidates = cls._module_candidates_from_target(target)
    if not candidates:
        return f"[Error: Could not derive import target from: {target}]"
    hits = []
    for rel_path, full_path in cls._iter_python_files(base_dir, file_pattern=file_pattern):
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                source = f.read()
            lines = source.splitlines()
            tree = ast.parse(source)
        except Exception:
            continue
        for entry in cls._collect_import_statements(tree, lines):
            matched = cls._match_import_target(entry, candidates)
            if matched:
                hits.append(f"{rel_path.replace('\\', '/')}:{entry['lineno']}: {entry['statement']} [matches {matched}]")
                if len(hits) >= max(1, int(max_results or 50)):
                    return "\n".join(hits)
    return "\n".join(hits) if hits else f"[No importers found for: {target}]"


def _json_value_kind(value):
    if isinstance(value, dict):
        return f"object ({len(value)} keys)"
    if isinstance(value, list):
        return f"array ({len(value)} items)"
    if value is None:
        return "null"
    return type(value).__name__


def _render_json_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _summarize_json(cls, value):
    if isinstance(value, dict):
        lines = [f"Type: object ({len(value)} keys)", "Top-level entries:"]
        items = list(value.items())
        for key, item in items[:50]:
            preview = cls._json_value_kind(item)
            if isinstance(item, (str, int, float, bool)) or item is None:
                preview += f" = {cls._render_json_value(item)}"
            lines.append(f"- {key}: {preview}")
        if len(items) > 50:
            lines.append(f"... ({len(items) - 50} more entries)")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = [f"Type: array ({len(value)} items)"]
        for idx, item in enumerate(value[:10]):
            lines.append(f"- [{idx}]: {cls._json_value_kind(item)}")
        if len(value) > 10:
            lines.append(f"... ({len(value) - 10} more items)")
        return "\n".join(lines)
    return f"Type: {cls._json_value_kind(value)}\nValue: {cls._render_json_value(value)}"


def _lookup_json_path(data, query):
    current = data
    for chunk in str(query or "").split('.'):
        if chunk == "":
            continue
        match = re.fullmatch(r'([^\[\]]+)?((?:\[[0-9]+\])*)', chunk)
        if not match:
            raise ValueError(f"Unsupported JSON query syntax: {query}")
        key, indexes = match.groups()
        if key:
            if not isinstance(current, dict) or key not in current:
                raise KeyError(f"JSON path segment not found: {key}")
            current = current[key]
        for raw_idx in re.findall(r'\[([0-9]+)\]', indexes or ''):
            idx = int(raw_idx)
            if not isinstance(current, list):
                raise TypeError(f"JSON path segment [{idx}] requires an array")
            if idx >= len(current):
                raise IndexError(f"JSON array index out of range: {idx}")
            current = current[idx]
    return current


def _render_line_excerpt(lines, start_line, end_line, with_line_numbers=False):
    total_lines = len(lines)
    start_idx = max(0, int(start_line or 1) - 1)
    end_idx = min(total_lines, int(end_line or total_lines))
    selected = lines[start_idx:end_idx]
    if with_line_numbers:
        width = max(2, len(str(max(total_lines, end_idx, 1))))
        return "".join(f"{start_idx + offset + 1:>{width}}: {line}" for offset, line in enumerate(selected))
    return "".join(selected)


def _load_python_ast(path):
    full_path = resolve_path(path)
    if not os.path.exists(full_path):
        return None, f"[Error: File not found: {path}]"
    if not full_path.endswith('.py'):
        return None, "[Info: Python symbol tools are only supported for .py files]"
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            source = f.read()
        return (full_path, source, source.splitlines(True), ast.parse(source)), None
    except Exception as e:
        return None, f"[Error parsing Python file: {e}]"


def _collect_python_symbols(tree):
    symbols = []
    def visit(nodes, stack):
        for node in nodes:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parent_kinds = [item['kind'] for item in stack]
            if isinstance(node, ast.ClassDef):
                kind = 'class'
            elif any(kind == 'class' for kind in parent_kinds):
                kind = 'async method' if isinstance(node, ast.AsyncFunctionDef) else 'method'
            elif any(kind in {'function', 'async function', 'nested function', 'async nested function', 'method', 'async method'} for kind in parent_kinds):
                kind = 'async nested function' if isinstance(node, ast.AsyncFunctionDef) else 'nested function'
            else:
                kind = 'async function' if isinstance(node, ast.AsyncFunctionDef) else 'function'
            entry = {
                'name': node.name,
                'qualified_name': '.'.join([item['name'] for item in stack] + [node.name]),
                'kind': kind,
                'lineno': int(getattr(node, 'lineno', 1)),
                'end_lineno': int(getattr(node, 'end_lineno', getattr(node, 'lineno', 1))),
                'depth': len(stack),
            }
            symbols.append(entry)
            visit(getattr(node, 'body', []), stack + [entry])
    visit(getattr(tree, 'body', []), [])
    return symbols


def _structure_label(kind):
    if kind == 'class':
        return 'Class'
    if 'method' in kind:
        return 'Method'
    if 'nested' in kind:
        return 'Nested Function'
    if kind == 'async function':
        return 'Async Function'
    return 'Function'


def _iter_python_files(cls, base_dir, file_pattern='*.py'):
    import fnmatch
    if os.path.isfile(base_dir):
        rel_name = os.path.basename(base_dir)
        if rel_name.endswith('.py') and fnmatch.fnmatch(rel_name, file_pattern or '*.py'):
            yield rel_name, base_dir
        return
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in cls.EXCLUDE_DIRS]
        for file_name in files:
            if not file_name.endswith('.py') or not fnmatch.fnmatch(file_name, file_pattern or '*.py'):
                continue
            full_path = os.path.join(root, file_name)
            yield os.path.relpath(full_path, base_dir), full_path


def _scan_python_symbols(cls, root_dir='.', file_pattern='*.py', predicate=None, max_results=50):
    base_dir = resolve_path(root_dir)
    if not os.path.exists(base_dir):
        raise FileNotFoundError(f"Path not found: {root_dir}")
    matches = []
    limit = max(1, int(max_results or 50))
    for rel_path, full_path in cls._iter_python_files(base_dir, file_pattern=file_pattern):
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())
        except Exception:
            continue
        for entry in cls._collect_python_symbols(tree):
            if predicate and not predicate(entry):
                continue
            matches.append((rel_path, entry))
            if len(matches) >= limit:
                return matches, base_dir
    return matches, base_dir


def _normalize_symbol_type(symbol_type):
    raw = str(symbol_type or '').strip().lower()
    if raw in {'', 'any', 'symbol'}:
        return None
    aliases = {'func': 'function', 'function': 'function', 'async function': 'function', 'method': 'method', 'async method': 'method', 'class': 'class'}
    return aliases.get(raw, raw)


def _symbol_matches_query(cls, entry, symbol, symbol_type=None):
    normalized_type = cls._normalize_symbol_type(symbol_type)
    entry_type = cls._normalize_symbol_type(entry['kind'])
    return (not normalized_type or entry_type == normalized_type) and (entry['name'] == symbol or entry['qualified_name'] == symbol)


def _resolve_symbol_query(entries, query):
    if '.' in query:
        return [entry for entry in entries if entry['qualified_name'] == query]
    return [entry for entry in entries if entry['name'] == query]


def _format_context_block(rel_path, lines, hit_line, context_lines=1):
    start = max(0, hit_line - context_lines - 1)
    end = min(len(lines), hit_line + context_lines)
    width = len(str(max(end, hit_line)))
    block = [f"{rel_path}:{hit_line}:"]
    for line_no in range(start, end):
        prefix = '>' if line_no + 1 == hit_line else ' '
        block.append(f"{prefix} {line_no + 1:>{width}} | {lines[line_no].rstrip()}")
    return '\n'.join(block)


def _collect_import_statements(cls, tree, lines):
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            statement = str(lines[node.lineno - 1]).strip() if node.lineno - 1 < len(lines) else 'import ...'
            for alias in node.names:
                imports.append({'lineno': int(getattr(node, 'lineno', 1)), 'statement': statement, 'category': cls._classify_module_reference(alias.name), 'matchable_modules': {alias.name.lower()}})
        elif isinstance(node, ast.ImportFrom):
            statement = str(lines[node.lineno - 1]).strip() if node.lineno - 1 < len(lines) else 'from ... import ...'
            module = node.module or ''
            dotted = ('.' * int(getattr(node, 'level', 0))) + module
            matchable = {dotted.lower()} if dotted else set()
            if int(getattr(node, 'level', 0)) == 0 and module:
                for alias in node.names:
                    if alias.name != '*':
                        matchable.add(f"{module}.{alias.name}".lower())
            imports.append({'lineno': int(getattr(node, 'lineno', 1)), 'statement': statement, 'category': cls._classify_module_reference(module, level=int(getattr(node, 'level', 0))), 'matchable_modules': matchable})
    imports.sort(key=lambda entry: (entry['lineno'], entry['statement']))
    return imports


def _classify_module_reference(module, level=0):
    if level > 0:
        return 'relative'
    module = str(module or '').strip()
    if not module:
        return 'relative'
    top = module.split('.', 1)[0]
    root = get_project_root()
    if os.path.exists(os.path.join(root, top)) or os.path.exists(os.path.join(root, f"{top}.py")):
        return 'internal'
    return 'external'


def _module_candidates_from_target(target):
    raw = str(target or '').strip()
    if not raw:
        return set()
    normalized = raw.replace('\\', '/').strip()
    candidates = {normalized.lower()}
    if '/' in normalized or normalized.endswith('.py'):
        full_path = resolve_path(normalized)
        try:
            rel_path = os.path.relpath(full_path, get_project_root())
        except Exception:
            rel_path = os.path.basename(full_path)
        rel_norm = rel_path.replace('\\', '/')
        if rel_norm.endswith('/__init__.py'):
            module_path = rel_norm[:-12]
        elif rel_norm.endswith('.py'):
            module_path = rel_norm[:-3]
        else:
            module_path = rel_norm
        module_name = module_path.replace('/', '.').strip('.')
        if module_name:
            candidates.add(module_name.lower())
            candidates.add(module_name.rsplit('.', 1)[-1].lower())
        if rel_norm:
            candidates.add(rel_norm.lower())
            stem = os.path.basename(rel_norm)
            if stem.endswith('.py'):
                candidates.add(stem[:-3].lower())
    elif '.' in normalized:
        candidates.add(normalized.rsplit('.', 1)[-1].lower())
    return {candidate for candidate in candidates if candidate}


def _match_import_target(entry, candidates):
    statement = entry.get('statement', '').lower()
    matchable = {item.lower() for item in entry.get('matchable_modules', set()) if item}
    for candidate in sorted(candidates, key=lambda item: (-len(item), item)):
        lowered = candidate.lower()
        if lowered in matchable:
            return lowered
        if any(item.startswith(lowered + '.') or lowered.startswith(item + '.') for item in matchable if item and not item.startswith('.')):
            return lowered
        if lowered in statement:
            return lowered
    return ''


def _build_test_search_terms(cls, query=None, source_path=None):
    terms = []
    def add(term):
        normalized = str(term or '').strip().replace('\\', '/').lower()
        if normalized and normalized not in terms:
            terms.append(normalized)
    if query:
        add(query)
        for piece in re.split(r'[^A-Za-z0-9_./]+', str(query)):
            if len(piece) >= 3:
                add(piece)
    if source_path:
        normalized = str(source_path).replace('\\', '/').strip()
        add(normalized)
        basename = os.path.basename(normalized)
        stem, _ext = os.path.splitext(basename)
        add(basename)
        add(stem)
        if '_' in stem:
            add(stem.replace('_', ''))
            for piece in stem.split('_'):
                if len(piece) >= 3:
                    add(piece)
        for candidate in cls._module_candidates_from_target(source_path):
            add(candidate)
    return terms


def _collect_test_entries(tree, lines):
    entries = []
    for node in getattr(tree, 'body', []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
            entries.append({'full_name': node.name, 'lineno': int(node.lineno), 'line_text': (lines[node.lineno - 1].strip() if node.lineno - 1 < len(lines) else '').lower()})
        elif isinstance(node, ast.ClassDef) and node.name.startswith('Test'):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith('test_'):
                    entries.append({'full_name': f"{node.name}.{child.name}", 'lineno': int(child.lineno), 'line_text': (lines[child.lineno - 1].strip() if child.lineno - 1 < len(lines) else '').lower()})
    return entries


def _score_test_match(rel_path, entry_names, source_lower, matched_terms):
    score = 0
    for term in matched_terms:
        if term in rel_path:
            score += 40
        if term in entry_names:
            score += 35
        if term in source_lower:
            score += 10
    return score