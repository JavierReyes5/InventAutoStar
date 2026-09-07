"""
Tests for inject_into_template and validate_output.
"""
import json
import textwrap
from datetime import date

import pytest

from update import (
    MONTH_ABBR_ES,
    PLACEHOLDER,
    OutputValidationError,
    TemplateError,
    inject_into_template,
    validate_output,
)
from conftest import SAMPLE_TEMPLATE_CONTENT, SAMPLE_VEHICLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_large_html(data_str: str = '{"vin":"TEST"}') -> str:
    """Return HTML > 10 KB that passes validate_output."""
    base = SAMPLE_TEMPLATE_CONTENT.replace(PLACEHOLDER, data_str)
    padding = "<!-- " + "x" * 11_000 + " -->"
    return base.replace("</body>", f"{padding}\n</body>")


def _inject(json_data: str = '{"vin":"TEST"}', update_date: date = date(2026, 8, 20)) -> str:
    return inject_into_template(SAMPLE_TEMPLATE_CONTENT, json_data, update_date)


# ---------------------------------------------------------------------------
# inject_into_template — placeholder replacement
# ---------------------------------------------------------------------------


def test_inject_replaces_placeholder():
    json_data = json.dumps(SAMPLE_VEHICLES, ensure_ascii=False)
    result = _inject(json_data)
    assert PLACEHOLDER not in result
    assert json_data in result


def test_inject_placeholder_not_present_after_inject():
    result = _inject('{"a":1}')
    assert "/*%%DATA%%*/" not in result


def test_inject_json_data_inside_const_data_array():
    json_data = '"testvalue"'
    result = _inject(json_data)
    assert f"const DATA = [{json_data}]" in result


# ---------------------------------------------------------------------------
# inject_into_template — date formatting
# ---------------------------------------------------------------------------


def test_inject_date_format_basic():
    result = inject_into_template(SAMPLE_TEMPLATE_CONTENT, "{}", date(2026, 8, 20))
    assert "20 ago 2026" in result


def test_inject_date_zero_padded_day():
    result = inject_into_template(SAMPLE_TEMPLATE_CONTENT, "{}", date(2026, 1, 5))
    assert "05 ene 2026" in result


def test_inject_date_december():
    result = inject_into_template(SAMPLE_TEMPLATE_CONTENT, "{}", date(2025, 12, 31))
    assert "31 dic 2025" in result


@pytest.mark.parametrize("month_num, abbr", enumerate(MONTH_ABBR_ES, start=1))
def test_inject_all_month_abbreviations(month_num, abbr):
    result = inject_into_template(SAMPLE_TEMPLATE_CONTENT, "{}", date(2026, month_num, 1))
    assert abbr in result


def test_inject_replaces_fecha_placeholder():
    assert "%%FECHA%%" not in _inject()


def test_inject_date_four_digit_year():
    result = inject_into_template(SAMPLE_TEMPLATE_CONTENT, "{}", date(2030, 6, 15))
    assert "2030" in result


# ---------------------------------------------------------------------------
# inject_into_template — TemplateError
# ---------------------------------------------------------------------------


def test_inject_no_placeholder_raises_template_error():
    template_without_placeholder = SAMPLE_TEMPLATE_CONTENT.replace(PLACEHOLDER, "")
    with pytest.raises(TemplateError):
        inject_into_template(template_without_placeholder, "{}", date.today())


def test_inject_two_placeholders_raises_template_error():
    template_double = SAMPLE_TEMPLATE_CONTENT + f"\n/* extra */ const X = [{PLACEHOLDER}];"
    with pytest.raises(TemplateError):
        inject_into_template(template_double, "{}", date.today())


def test_inject_zero_placeholders_error_message():
    no_placeholder = "<!DOCTYPE html><html></html>"
    with pytest.raises(TemplateError) as exc_info:
        inject_into_template(no_placeholder, "{}", date.today())
    assert "0" in str(exc_info.value)


def test_inject_two_placeholders_error_message():
    two = f"[{PLACEHOLDER}] [{PLACEHOLDER}]"
    with pytest.raises(TemplateError) as exc_info:
        inject_into_template(two, "{}", date.today())
    assert "2" in str(exc_info.value)


# ---------------------------------------------------------------------------
# inject_into_template — structure preservation
# ---------------------------------------------------------------------------


def test_inject_css_preserved():
    result = _inject()
    assert "--amber: #C2185B" in result


def test_inject_html_structure_preserved():
    result = _inject()
    assert "<div class=\"wrap\">" in result
    assert "<header>" in result


def test_inject_javascript_preserved():
    result = _inject()
    assert "function render()" in result


# ---------------------------------------------------------------------------
# validate_output — valid HTML passes
# ---------------------------------------------------------------------------


def test_validate_output_valid_html_passes():
    html = _make_large_html(json.dumps(SAMPLE_VEHICLES, ensure_ascii=False))
    # Should not raise
    validate_output(html)


def test_validate_output_single_element_passes():
    html = _make_large_html('{"vin":"V1","kms":0,"precio":0.0}')
    validate_output(html)


# ---------------------------------------------------------------------------
# validate_output — missing DATA marker
# ---------------------------------------------------------------------------


def test_validate_output_missing_const_data_raises():
    html = "<html><body>" + "x" * 15_000 + "</body></html>"
    with pytest.raises(OutputValidationError):
        validate_output(html)


def test_validate_output_wrong_marker_raises():
    # Has "var DATA" but not "const DATA = ["
    html = "var DATA = [{}];" + "x" * 15_000
    with pytest.raises(OutputValidationError):
        validate_output(html)


# ---------------------------------------------------------------------------
# validate_output — empty array
# ---------------------------------------------------------------------------


def test_validate_output_empty_array_raises():
    html = "const DATA = [];" + "x" * 15_000
    with pytest.raises(OutputValidationError):
        validate_output(html)


def test_validate_output_whitespace_only_array_raises():
    html = "const DATA = [   ];" + "x" * 15_000
    with pytest.raises(OutputValidationError):
        validate_output(html)


# ---------------------------------------------------------------------------
# validate_output — size check
# ---------------------------------------------------------------------------


def test_validate_output_small_html_raises():
    # A tiny HTML with DATA but < 10 KB
    html = 'const DATA = [{"vin":"V1"}];'
    with pytest.raises(OutputValidationError) as exc_info:
        validate_output(html)
    assert "10240" in str(exc_info.value) or "bytes" in str(exc_info.value)


def test_validate_output_exactly_10kb_raises():
    # Build HTML that is exactly 10 KB (10240 bytes) — should fail (must be > 10 KB)
    base = 'const DATA = [{"vin":"V1"}];'
    html = base.ljust(10240)
    assert len(html.encode("utf-8")) == 10240
    with pytest.raises(OutputValidationError):
        validate_output(html)


def test_validate_output_just_over_10kb_with_data_passes():
    # 10241 bytes with valid data marker
    base = 'const DATA = [{"vin":"V1"}];'
    padding = "x" * (10241 - len(base.encode("utf-8")))
    html = base + padding
    validate_output(html)
