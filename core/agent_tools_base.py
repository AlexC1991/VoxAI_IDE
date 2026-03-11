import logging
import os


log = logging.getLogger(__name__)


_project_root = None


def set_project_root(path):
    global _project_root
    _project_root = os.path.realpath(path)
    log.info("Project root set to: %s", _project_root)


def get_ide_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path):
    return os.path.join(get_ide_root(), relative_path)


def get_project_root():
    global _project_root
    if _project_root is None:
        _project_root = os.path.realpath(os.getcwd())
    return _project_root


def resolve_path(path, default_to_project=True):
    if path in (None, ""):
        return get_project_root() if default_to_project else os.path.realpath(os.getcwd())
    if os.path.isabs(path):
        return os.path.realpath(os.path.abspath(path))
    base = get_project_root() if default_to_project else os.getcwd()
    return os.path.realpath(os.path.join(base, path))


def _is_inside_project(path):
    real = resolve_path(path)
    root = get_project_root()
    try:
        return os.path.commonpath([real, root]) == root
    except ValueError:
        return False


def _require_inside_project(path, action="modify"):
    if not _is_inside_project(path):
        raise PermissionError(
            f"Cannot {action} '{path}' — it is outside the project directory ({get_project_root()}). "
            f"Only read operations are allowed outside the project."
        )