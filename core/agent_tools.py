from core.agent_tools_base import (
    get_executable_root,
    get_ide_root,
    get_project_root,
    get_resource_path,
    resolve_path,
    set_project_root,
)
from core.agent_tools_edit import (
    _anchor_bounds,
    _common_indent,
    _edit_usage_error,
    _find_edit_matches,
    _find_indentation_aware_match,
    _find_indentation_aware_matches,
    _plan_edit,
    _plan_line_range_edit,
    _reindent_like_match,
    _select_single_edit_match,
    copy_file,
    delete_file,
    edit_file,
    execute_command,
    get_diff,
    move_file,
    preview_edit,
    validate_syntax,
    write_file,
)
from core.agent_tools_read_search import (
    _build_test_search_terms,
    _classify_module_reference,
    _collect_import_statements,
    _collect_python_symbols,
    _collect_test_entries,
    _format_context_block,
    _iter_python_files,
    _json_value_kind,
    _load_python_ast,
    _lookup_json_path,
    _match_import_target,
    _module_candidates_from_target,
    _normalize_symbol_type,
    _render_json_value,
    _render_line_excerpt,
    _resolve_symbol_query,
    _scan_python_symbols,
    _score_test_match,
    _structure_label,
    _summarize_json,
    _symbol_matches_query,
    find_files,
    find_importers,
    find_references,
    find_symbol,
    find_tests,
    get_file_structure,
    get_imports,
    list_files,
    read_file,
    read_json,
    read_python_symbols,
    search_files,
)


class AgentToolHandler:
    EXCLUDE_DIRS = {
        '.git', '__pycache__', '.idea', 'venv', 'env',
        '.gemini', 'node_modules', 'target', 'build', 'dist',
    }

    resolve_path = staticmethod(resolve_path)
    read_file = classmethod(read_file)
    list_files = classmethod(list_files)
    find_files = classmethod(find_files)
    search_files = classmethod(search_files)
    read_json = classmethod(read_json)
    get_file_structure = classmethod(get_file_structure)
    find_symbol = classmethod(find_symbol)
    find_references = classmethod(find_references)
    read_python_symbols = classmethod(read_python_symbols)
    find_tests = classmethod(find_tests)
    get_imports = classmethod(get_imports)
    find_importers = classmethod(find_importers)

    write_file = staticmethod(write_file)
    move_file = staticmethod(move_file)
    copy_file = staticmethod(copy_file)
    delete_file = staticmethod(delete_file)
    execute_command = staticmethod(execute_command)
    preview_edit = classmethod(preview_edit)
    edit_file = classmethod(edit_file)

    _plan_edit = classmethod(_plan_edit)
    _plan_line_range_edit = classmethod(_plan_line_range_edit)
    _anchor_bounds = classmethod(_anchor_bounds)
    _find_edit_matches = classmethod(_find_edit_matches)
    _select_single_edit_match = classmethod(_select_single_edit_match)
    _edit_usage_error = staticmethod(_edit_usage_error)
    _common_indent = staticmethod(_common_indent)
    _find_indentation_aware_matches = classmethod(_find_indentation_aware_matches)
    _find_indentation_aware_match = classmethod(_find_indentation_aware_match)
    _reindent_like_match = classmethod(_reindent_like_match)

    _json_value_kind = staticmethod(_json_value_kind)
    _render_json_value = staticmethod(_render_json_value)
    _summarize_json = classmethod(_summarize_json)
    _lookup_json_path = staticmethod(_lookup_json_path)
    _render_line_excerpt = staticmethod(_render_line_excerpt)
    _load_python_ast = staticmethod(_load_python_ast)
    _collect_python_symbols = staticmethod(_collect_python_symbols)
    _structure_label = staticmethod(_structure_label)
    _iter_python_files = classmethod(_iter_python_files)
    _scan_python_symbols = classmethod(_scan_python_symbols)
    _normalize_symbol_type = staticmethod(_normalize_symbol_type)
    _symbol_matches_query = classmethod(_symbol_matches_query)
    _resolve_symbol_query = staticmethod(_resolve_symbol_query)
    _format_context_block = staticmethod(_format_context_block)
    _collect_import_statements = classmethod(_collect_import_statements)
    _classify_module_reference = staticmethod(_classify_module_reference)
    _module_candidates_from_target = staticmethod(_module_candidates_from_target)
    _match_import_target = staticmethod(_match_import_target)
    _build_test_search_terms = classmethod(_build_test_search_terms)
    _collect_test_entries = staticmethod(_collect_test_entries)
    _score_test_match = staticmethod(_score_test_match)
    validate_syntax = staticmethod(validate_syntax)
    get_diff = staticmethod(get_diff)


__all__ = [
    'AgentToolHandler',
    'get_executable_root',
    'get_ide_root',
    'get_project_root',
    'get_resource_path',
    'resolve_path',
    'set_project_root',
]