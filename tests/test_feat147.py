"""
FEAT-147 — Unit tests for safety.get_param_names.

Covers: annotations, defaults, *args/**kwargs, multiple defs,
unicode identifiers, and syntactically-invalid source.
"""

from pringle.ast_utils import get_param_names


class TestGetParamNames:
    def test_simple_args(self):
        assert get_param_names("def f(a, b, c): pass") == {"a", "b", "c"}

    def test_annotation_excluded(self):
        # Only the param name, not the annotation type
        result = get_param_names("def f(k: int, β: array): pass")
        assert result == {"k", "β"}

    def test_default_values(self):
        result = get_param_names("def f(x, y=0): pass")
        assert result == {"x", "y"}

    def test_vararg(self):
        result = get_param_names("def f(*args): pass")
        assert "args" in result

    def test_kwarg(self):
        result = get_param_names("def f(**kwargs): pass")
        assert "kwargs" in result

    def test_kwonly(self):
        result = get_param_names("def f(*, key): pass")
        assert "key" in result

    def test_posonly(self):
        result = get_param_names("def f(a, /, b): pass")
        assert result == {"a", "b"}

    def test_multiple_defs(self):
        src = "def f(a, b): pass\ndef g(c, d): pass"
        result = get_param_names(src)
        assert result == {"a", "b", "c", "d"}

    def test_unicode_param(self):
        result = get_param_names("def f(β, η): pass")
        assert result == {"β", "η"}

    def test_lambda_params(self):
        result = get_param_names("g = lambda x, y: x + y")
        assert result == {"x", "y"}

    def test_syntax_error_returns_empty(self):
        assert get_param_names("def f(") == set()

    def test_no_def_returns_empty(self):
        assert get_param_names("z = x**2 + y**2") == set()

    def test_full_bifurcate_signature(self):
        src = "def bifurcate(memories, k: int, T: int, β: array): pass"
        result = get_param_names(src)
        assert result == {"memories", "k", "T", "β"}
