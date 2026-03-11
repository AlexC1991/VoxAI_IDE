import os

from core.agent_tools_base import _require_inside_project, get_project_root, resolve_path


def write_file(path, content):
    full_path = resolve_path(path)
    try:
        _require_inside_project(full_path, action="write to")
    except PermissionError as e:
        return f"[Permission Denied: {e}]"
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"[Success: File written to {full_path}]"
    except Exception as e:
        return f"[Error writing file: {e}]"


def move_file(src, dst):
    import shutil
    src_path = resolve_path(src)
    dst_path = resolve_path(dst)
    try:
        _require_inside_project(src_path, action="move from")
        _require_inside_project(dst_path, action="move to")
    except PermissionError as e:
        return f"[Permission Denied: {e}]"
    try:
        dst_dir = os.path.dirname(dst_path)
        if dst_dir and not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)
        shutil.move(src_path, dst_path)
        return f"[Success: Moved '{src}' to '{dst}']"
    except Exception as e:
        return f"[Error moving file: {e}]"


def copy_file(src, dst):
    import shutil
    src_path = resolve_path(src)
    dst_path = resolve_path(dst)
    try:
        _require_inside_project(dst_path, action="copy to")
    except PermissionError as e:
        return f"[Permission Denied: {e}]"
    try:
        dst_dir = os.path.dirname(dst_path)
        if dst_dir and not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        return f"[Success: Copied '{src}' to '{dst}']"
    except Exception as e:
        return f"[Error copying file: {e}]"


def delete_file(path):
    import shutil
    full_path = resolve_path(path)
    try:
        _require_inside_project(full_path, action="delete")
    except PermissionError as e:
        return f"[Permission Denied: {e}]"
    try:
        if os.path.isfile(full_path):
            os.remove(full_path)
            return f"[Success: Deleted file '{path}']"
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
            return f"[Success: Deleted directory '{path}']"
        return f"[Error: Path not found '{path}']"
    except Exception as e:
        return f"[Error deleting '{path}': {e}]"


def execute_command(command, cwd=None, timeout=120):
    import subprocess
    effective_cwd = resolve_path(cwd) if cwd not in (None, "") else get_project_root()
    try:
        _require_inside_project(effective_cwd, action="execute commands in")
    except PermissionError as e:
        return f"[Permission Denied: {e}]"
    try:
        result = subprocess.run(command, shell=True, cwd=effective_cwd, capture_output=True, text=True, timeout=timeout)
        max_cmd_output = 6000
        output = ""
        if result.stdout:
            stdout = result.stdout
            if len(stdout) > max_cmd_output:
                stdout = stdout[:2000] + f"\n... [{len(stdout) - 4000} chars truncated] ...\n" + stdout[-2000:]
            output += f"STDOUT:\n{stdout}"
        if result.stderr:
            stderr = result.stderr
            if len(stderr) > max_cmd_output:
                stderr = stderr[-max_cmd_output:]
            output += f"\nSTDERR:\n{stderr}"
        if result.returncode != 0:
            output += f"\n[Exit code: {result.returncode}]"
        return output.strip() or "[Command completed with no output]"
    except subprocess.TimeoutExpired:
        return f"[Error: Command timed out after {timeout}s. Consider running it manually.]"
    except Exception as e:
        return f"[Error executing command: {e}]"


def preview_edit(cls, path, old_text="", new_text="", start_line=None, end_line=None, match_mode="smart", occurrence=None, replace_all=False, anchor_before="", anchor_after="", insert_before="", insert_after=""):
    full_path = resolve_path(path)
    try:
        _require_inside_project(full_path, action="edit")
    except PermissionError as e:
        return {"error": f"[Permission Denied: {e}]"}
    if not os.path.exists(full_path):
        return {"error": f"[Error: File not found: {full_path}]"}
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        plan = cls._plan_edit(content, path=path, old_text=old_text, new_text=new_text, start_line=start_line, end_line=end_line, match_mode=match_mode, occurrence=occurrence, replace_all=replace_all, anchor_before=anchor_before, anchor_after=anchor_after, insert_before=insert_before, insert_after=insert_after)
        plan['full_path'] = full_path
        plan['old_content'] = content
        return plan
    except Exception as e:
        return {"error": f"[Error editing file: {e}]"}


def edit_file(cls, path, old_text="", new_text="", start_line=None, end_line=None, match_mode="smart", occurrence=None, replace_all=False, anchor_before="", anchor_after="", insert_before="", insert_after=""):
    plan = cls.preview_edit(path, old_text=old_text, new_text=new_text, start_line=start_line, end_line=end_line, match_mode=match_mode, occurrence=occurrence, replace_all=replace_all, anchor_before=anchor_before, anchor_after=anchor_after, insert_before=insert_before, insert_after=insert_after)
    if plan.get('error'):
        return plan['error']
    if not plan.get('changed'):
        return f"[No changes made: {plan.get('summary', 'edit produced no content change')}]"
    syntax_error = cls.validate_syntax(plan.get('new_content', ''), path)
    if syntax_error:
        return f"[Error: edit would introduce invalid syntax in {path}: {syntax_error}]"
    try:
        with open(plan['full_path'], 'w', encoding='utf-8') as f:
            f.write(plan['new_content'])
        return f"[Success: Edited {plan['full_path']} using {plan.get('method', 'edit')} — {plan.get('summary', 'applied edit')}]"
    except Exception as e:
        return f"[Error editing file: {e}]"


def _plan_edit(cls, content, *, path, old_text="", new_text="", start_line=None, end_line=None, match_mode="smart", occurrence=None, replace_all=False, anchor_before="", anchor_after="", insert_before="", insert_after=""):
    old_text = "" if old_text is None else str(old_text)
    new_text = "" if new_text is None else str(new_text)
    match_mode = str(match_mode or 'smart').strip().lower() or 'smart'
    replace_all = str(replace_all).lower() == 'true' if isinstance(replace_all, str) else bool(replace_all)
    if occurrence in ('', None):
        occurrence = None
    else:
        try:
            occurrence = int(occurrence)
        except (TypeError, ValueError):
            return {'error': f"[Error: occurrence must be an integer in edit_file for {path}]"}
        if occurrence < 1:
            return {'error': f"[Error: occurrence must be >= 1 in edit_file for {path}]"}
    if insert_before and insert_after:
        return {'error': f"[Error: edit_file for {path} cannot use both insert_before and insert_after in the same call]"}
    if start_line not in (None, '') or end_line not in (None, ''):
        return cls._plan_line_range_edit(content, path, new_text, start_line=start_line, end_line=end_line)
    if insert_before or insert_after:
        anchor_text = str(insert_before or insert_after)
        anchor_role = 'insert_before' if insert_before else 'insert_after'
        anchor_plan = cls._select_single_edit_match(cls._find_edit_matches(content, anchor_text, match_mode=match_mode), path, target_label=anchor_role, occurrence=occurrence, replace_all=False)
        if anchor_plan.get('error'):
            return anchor_plan
        anchor_match = anchor_plan['matches'][0]
        insert_at = anchor_match['start'] if insert_before else anchor_match['end']
        new_content = content[:insert_at] + new_text + content[insert_at:]
        return {'changed': new_content != content, 'new_content': new_content, 'method': anchor_role, 'summary': f"inserted {len(new_text)} chars {anchor_role} in {path}"}
    if not old_text:
        return {'error': cls._edit_usage_error(path, 'edit_file needs one of: old_text/new_text, start_line/end_line, insert_before, or insert_after.')}
    bounds = cls._anchor_bounds(content, path, anchor_before=anchor_before, anchor_after=anchor_after, match_mode=match_mode)
    if bounds.get('error'):
        return bounds
    matches = [match for match in cls._find_edit_matches(content, old_text, match_mode=match_mode) if match['start'] >= bounds.get('start', 0) and match['end'] <= bounds.get('end', len(content))]
    if not matches:
        if new_text and new_text in content and old_text not in content:
            return {'changed': False, 'new_content': content, 'method': 'smart-match', 'summary': f"replacement text already exists in {path}; old_text was not found"}
        return {'error': cls._edit_usage_error(path, f"could not locate the requested edit target in {path}")}
    selection = cls._select_single_edit_match(matches, path, target_label='edit target', occurrence=occurrence, replace_all=replace_all)
    if selection.get('error'):
        return selection
    chosen = selection.get('matches', [])
    new_content = content
    for match in sorted(chosen, key=lambda item: item['start'], reverse=True):
        replacement = cls._reindent_like_match(old_text, new_text, match.get('matched_text', '')) if match.get('method') == 'indentation-aware' else new_text
        new_content = new_content[:match['start']] + replacement + new_content[match['end']:]
    return {'changed': new_content != content, 'new_content': new_content, 'method': ', '.join(sorted({match.get('method', 'smart-match') for match in chosen})), 'summary': f"applied {len(chosen)} replacement(s) in {path}"}


def _plan_line_range_edit(cls, content, path, new_text, *, start_line=None, end_line=None):
    try:
        start = int(start_line or end_line)
        end = int(end_line or start_line or start)
    except (TypeError, ValueError):
        return {'error': f"[Error: start_line/end_line must be integers in edit_file for {path}]"}
    if start < 1 or end < start:
        return {'error': f"[Error: invalid line range {start}-{end} for edit_file on {path}]"}
    lines = str(content or '').splitlines(keepends=True)
    if end > len(lines):
        return {'error': f"[Error: line range {start}-{end} is outside {path} ({len(lines)} lines)]"}
    new_content = ''.join(lines[:start - 1]) + new_text + ''.join(lines[end:])
    return {'changed': new_content != content, 'new_content': new_content, 'method': 'line-range', 'summary': f"replaced lines {start}-{end} in {path}"}


def _anchor_bounds(cls, content, path, *, anchor_before="", anchor_after="", match_mode="smart"):
    start = 0
    end = len(content)
    if anchor_before:
        selection = cls._select_single_edit_match(cls._find_edit_matches(content, anchor_before, match_mode=match_mode), path, target_label='anchor_before')
        if selection.get('error'):
            return selection
        start = selection['matches'][0]['end']
    if anchor_after:
        selection = cls._select_single_edit_match(cls._find_edit_matches(content, anchor_after, match_mode=match_mode), path, target_label='anchor_after')
        if selection.get('error'):
            return selection
        end = selection['matches'][0]['start']
    if start > end:
        return {'error': f"[Error: anchor_before appears after anchor_after in {path}]"}
    return {'start': start, 'end': end}


def _find_edit_matches(cls, content, old_text, match_mode='smart'):
    content = str(content or '')
    old_text = str(old_text or '')
    if not old_text:
        return []
    matches = []
    seen = set()
    def add_match(start, end, matched_text, method):
        key = (start, end)
        if key not in seen:
            seen.add(key)
            matches.append({'start': start, 'end': end, 'matched_text': matched_text, 'method': method})
    start_idx = 0
    while True:
        idx = content.find(old_text, start_idx)
        if idx < 0:
            break
        add_match(idx, idx + len(old_text), old_text, 'exact')
        start_idx = idx + max(1, len(old_text))
    if matches or match_mode == 'exact':
        return sorted(matches, key=lambda item: (item['start'], item['end']))
    trimmed = old_text.rstrip('\r\n')
    if trimmed and trimmed != old_text:
        start_idx = 0
        while True:
            idx = content.find(trimmed, start_idx)
            if idx < 0:
                break
            add_match(idx, idx + len(trimmed), trimmed, 'trimmed-newline')
            start_idx = idx + max(1, len(trimmed))
    if matches:
        return sorted(matches, key=lambda item: (item['start'], item['end']))
    for start, end, matched_text in cls._find_indentation_aware_matches(content, old_text):
        add_match(start, end, matched_text, 'indentation-aware')
    return sorted(matches, key=lambda item: (item['start'], item['end']))


def _select_single_edit_match(cls, matches, path, *, target_label, occurrence=None, replace_all=False):
    if not matches:
        return {'error': cls._edit_usage_error(path, f"could not locate {target_label} in {path}")}
    if replace_all:
        return {'matches': matches}
    if occurrence is not None:
        if occurrence > len(matches):
            return {'error': f"[Error: {target_label} occurrence {occurrence} was requested in {path}, but only {len(matches)} match(es) were found]"}
        return {'matches': [matches[occurrence - 1]]}
    if len(matches) > 1:
        return {'error': cls._edit_usage_error(path, f"{target_label} matched {len(matches)} locations in {path}; use more surrounding context, line numbers, anchor_before/anchor_after, occurrence, or replace_all")}
    return {'matches': [matches[0]]}


def _edit_usage_error(path, problem):
    return (
        f"[Error: {problem}. edit_file is easiest in one of these forms for {path}: "
        f"(1) exact replace with old_text/new_text, "
        f"(2) line-range replace with start_line/end_line plus block content, or "
        f"(3) insert_before/insert_after anchor plus block content. "
        f"If needed, run read_file with with_line_numbers=\"true\" first to copy the live text or line numbers exactly.]"
    )


def _common_indent(text):
    indents = []
    for line in str(text or '').splitlines():
        if not line.strip():
            continue
        stripped = line.lstrip(' \t')
        indents.append(line[:len(line) - len(stripped)])
    if not indents:
        return ''
    prefix = indents[0]
    for indent in indents[1:]:
        while prefix and not indent.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            break
    return prefix


def _find_indentation_aware_matches(cls, content, old_text):
    old_lines = str(old_text or '').splitlines(keepends=True)
    content_lines = str(content or '').splitlines(keepends=True)
    if not old_lines or len(old_lines) > len(content_lines):
        return []
    def _normalized(lines):
        return [line.rstrip('\r\n').lstrip(' \t') for line in lines]
    normalized_old = _normalized(old_lines)
    matches = []
    char_offset = 0
    window_len = len(old_lines)
    for start in range(len(content_lines) - window_len + 1):
        if start > 0:
            char_offset += len(content_lines[start - 1])
        window = content_lines[start:start + window_len]
        if _normalized(window) == normalized_old:
            matched_text = ''.join(window)
            matches.append((char_offset, char_offset + len(matched_text), matched_text))
    return matches


def _find_indentation_aware_match(cls, content, old_text):
    matches = cls._find_indentation_aware_matches(content, old_text)
    return matches[0] if len(matches) == 1 else None


def _reindent_like_match(cls, old_text, new_text, matched_text):
    source_indent = cls._common_indent(old_text)
    target_indent = cls._common_indent(matched_text)
    if source_indent == target_indent:
        return new_text
    adjusted = []
    for line in str(new_text or '').splitlines(keepends=True):
        if not line.strip():
            adjusted.append(line)
            continue
        candidate = line[len(source_indent):] if source_indent and line.startswith(source_indent) else line
        adjusted.append(f"{target_indent}{candidate}")
    return ''.join(adjusted)


def validate_syntax(code, filename):
    _, ext = os.path.splitext(filename)
    if ext == '.py':
        try:
            compile(code, filename, 'exec')
            return None
        except SyntaxError as e:
            return f"SyntaxError line {e.lineno}: {e.msg}"
    return None


def get_diff(old_content, new_content, filename):
    import difflib
    diff = difflib.unified_diff(old_content.splitlines(), new_content.splitlines(), fromfile=f"a/{filename}", tofile=f"b/{filename}", n=3)
    return '\n'.join(list(diff))