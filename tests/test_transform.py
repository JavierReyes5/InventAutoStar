"""
Tests for transform_row, filter_and_deduplicate, and normalize_grupo.
"""
import pytest

from update import (
    filter_and_deduplicate,
    normalize_grupo,
    transform_row,
)
from conftest import SAMPLE_ROW_VALID


# ---------------------------------------------------------------------------
# transform_row — correct types
# ---------------------------------------------------------------------------


def test_transform_row_kms_is_int():
    row = {**SAMPLE_ROW_VALID, "kms": "30000"}
    result = transform_row(row)
    assert isinstance(result["kms"], int)
    assert result["kms"] == 30000


def test_transform_row_precio_is_float():
    row = {**SAMPLE_ROW_VALID, "precio": "350000.0"}
    result = transform_row(row)
    assert isinstance(result["precio"], float)
    assert result["precio"] == 350000.0


def test_transform_row_string_fields_stripped():
    row = {**SAMPLE_ROW_VALID, "desc": "  TOYOTA COROLLA  ", "color": " BLANCO "}
    result = transform_row(row)
    assert result["desc"] == "TOYOTA COROLLA"
    assert result["color"] == "BLANCO"


def test_transform_row_all_required_keys_present():
    result = transform_row(SAMPLE_ROW_VALID)
    expected_keys = {
        "vin", "inv", "desc", "anio", "kms", "color", "precio",
        "bono", "garantia", "ubicacion", "grupo", "condicion",
        "link", "tipo", "estatus", "foraneo", "cil", "lts", "trans",
    }
    assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# transform_row — precio coercion
# ---------------------------------------------------------------------------


def test_transform_row_precio_invalido_texto():
    row = {**SAMPLE_ROW_VALID, "precio": "no-es-numero"}
    assert transform_row(row)["precio"] == 0.0


def test_transform_row_precio_vacio():
    row = {**SAMPLE_ROW_VALID, "precio": ""}
    assert transform_row(row)["precio"] == 0.0


def test_transform_row_precio_solo_espacios():
    row = {**SAMPLE_ROW_VALID, "precio": "   "}
    assert transform_row(row)["precio"] == 0.0


def test_transform_row_precio_negativo():
    row = {**SAMPLE_ROW_VALID, "precio": "-5000"}
    assert transform_row(row)["precio"] == 0.0


def test_transform_row_precio_con_simbolo_pesos():
    """$350,000.00 should parse correctly."""
    row = {**SAMPLE_ROW_VALID, "precio": "$350,000.00"}
    assert transform_row(row)["precio"] == 350000.0


def test_transform_row_precio_con_comas():
    row = {**SAMPLE_ROW_VALID, "precio": "1,250,000.50"}
    assert transform_row(row)["precio"] == 1250000.50


# ---------------------------------------------------------------------------
# transform_row — kms coercion
# ---------------------------------------------------------------------------


def test_transform_row_kms_invalido_texto():
    row = {**SAMPLE_ROW_VALID, "kms": "abc"}
    assert transform_row(row)["kms"] == 0


def test_transform_row_kms_vacio():
    row = {**SAMPLE_ROW_VALID, "kms": ""}
    assert transform_row(row)["kms"] == 0


def test_transform_row_kms_negativo():
    row = {**SAMPLE_ROW_VALID, "kms": "-100"}
    assert transform_row(row)["kms"] == 0


def test_transform_row_kms_cero():
    row = {**SAMPLE_ROW_VALID, "kms": "0"}
    assert transform_row(row)["kms"] == 0


def test_transform_row_kms_con_coma():
    row = {**SAMPLE_ROW_VALID, "kms": "30,000"}
    assert transform_row(row)["kms"] == 30000


def test_transform_row_kms_flotante_string():
    """CSV might have "30000.0" — int("30000.0") fails but we only try int()."""
    row = {**SAMPLE_ROW_VALID, "kms": "30000.5"}
    # "30000.5" cannot be parsed as int → 0
    assert transform_row(row)["kms"] == 0


# ---------------------------------------------------------------------------
# transform_row — optional empty fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["bono", "garantia", "condicion", "link", "foraneo", "cil", "lts", "trans"])
def test_transform_row_optional_empty(field):
    row = {**SAMPLE_ROW_VALID, field: ""}
    assert transform_row(row)[field] == ""


@pytest.mark.parametrize("field", ["bono", "garantia", "condicion", "link", "foraneo", "cil", "lts", "trans"])
def test_transform_row_optional_whitespace(field):
    row = {**SAMPLE_ROW_VALID, field: "   "}
    assert transform_row(row)[field] == ""


@pytest.mark.parametrize("field", ["bono", "garantia", "condicion", "link", "foraneo", "cil", "lts", "trans"])
def test_transform_row_optional_with_value(field):
    row = {**SAMPLE_ROW_VALID, field: "  VALOR  "}
    assert transform_row(row)[field] == "VALOR"


# ---------------------------------------------------------------------------
# filter_and_deduplicate — VIN vacío
# ---------------------------------------------------------------------------


def test_filter_empty_vin_omitted():
    rows = [
        {**SAMPLE_ROW_VALID, "vin": ""},
        {**SAMPLE_ROW_VALID, "vin": "ABC123"},
    ]
    valid, empty_indices, _ = filter_and_deduplicate(rows)
    assert len(valid) == 1
    assert valid[0]["vin"] == "ABC123"


def test_filter_empty_vin_indices_are_one_based():
    rows = [
        {**SAMPLE_ROW_VALID, "vin": ""},        # index 1
        {**SAMPLE_ROW_VALID, "vin": "ABC123"},  # index 2
        {**SAMPLE_ROW_VALID, "vin": ""},        # index 3
    ]
    _, empty_indices, _ = filter_and_deduplicate(rows)
    assert empty_indices == [1, 3]


def test_filter_whitespace_vin_treated_as_empty():
    rows = [{**SAMPLE_ROW_VALID, "vin": "   "}]
    valid, empty_indices, _ = filter_and_deduplicate(rows)
    assert valid == []
    assert empty_indices == [1]


def test_filter_no_empty_vins():
    rows = [
        {**SAMPLE_ROW_VALID, "vin": "A001"},
        {**SAMPLE_ROW_VALID, "vin": "A002"},
    ]
    valid, empty_indices, dup_vins = filter_and_deduplicate(rows)
    assert len(valid) == 2
    assert empty_indices == []
    assert dup_vins == []


# ---------------------------------------------------------------------------
# filter_and_deduplicate — duplicados
# ---------------------------------------------------------------------------


def test_filter_duplicate_vin_keeps_first():
    rows = [
        {**SAMPLE_ROW_VALID, "vin": "DUP001", "desc": "PRIMERA"},
        {**SAMPLE_ROW_VALID, "vin": "DUP001", "desc": "SEGUNDA"},
    ]
    valid, _, dup_vins = filter_and_deduplicate(rows)
    assert len(valid) == 1
    assert valid[0]["desc"] == "PRIMERA"
    assert dup_vins == ["DUP001"]


def test_filter_triple_duplicate_reports_two():
    rows = [
        {**SAMPLE_ROW_VALID, "vin": "DUP", "desc": "1"},
        {**SAMPLE_ROW_VALID, "vin": "DUP", "desc": "2"},
        {**SAMPLE_ROW_VALID, "vin": "DUP", "desc": "3"},
    ]
    valid, _, dup_vins = filter_and_deduplicate(rows)
    assert len(valid) == 1
    assert dup_vins == ["DUP", "DUP"]


def test_filter_different_vins_all_kept():
    rows = [
        {**SAMPLE_ROW_VALID, "vin": "A001"},
        {**SAMPLE_ROW_VALID, "vin": "A002"},
        {**SAMPLE_ROW_VALID, "vin": "A003"},
    ]
    valid, _, dup_vins = filter_and_deduplicate(rows)
    assert len(valid) == 3
    assert dup_vins == []


def test_filter_empty_list():
    valid, empty_indices, dup_vins = filter_and_deduplicate([])
    assert valid == []
    assert empty_indices == []
    assert dup_vins == []


def test_filter_mixed_empty_and_duplicates():
    rows = [
        {**SAMPLE_ROW_VALID, "vin": ""},         # 1 — empty
        {**SAMPLE_ROW_VALID, "vin": "VIN1"},     # 2 — ok
        {**SAMPLE_ROW_VALID, "vin": "VIN1"},     # 3 — dup
        {**SAMPLE_ROW_VALID, "vin": ""},         # 4 — empty
        {**SAMPLE_ROW_VALID, "vin": "VIN2"},     # 5 — ok
    ]
    valid, empty_indices, dup_vins = filter_and_deduplicate(rows)
    assert [r["vin"] for r in valid] == ["VIN1", "VIN2"]
    assert empty_indices == [1, 4]
    assert dup_vins == ["VIN1"]


# ---------------------------------------------------------------------------
# normalize_grupo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grupo_valido", ["Mexicali", "Tijuana", "Otro"])
def test_normalize_grupo_valido_sin_cambio(grupo_valido):
    records = [{**SAMPLE_ROW_VALID, "vin": "V001", "grupo": grupo_valido}]
    normalized, invalids = normalize_grupo(records)
    assert normalized[0]["grupo"] == grupo_valido
    assert invalids == []


def test_normalize_grupo_invalido_corregido_a_otro():
    records = [{**SAMPLE_ROW_VALID, "vin": "V001", "grupo": "Ensenada"}]
    normalized, invalids = normalize_grupo(records)
    assert normalized[0]["grupo"] == "Otro"
    assert invalids == [("V001", "Ensenada")]


def test_normalize_grupo_vacio_corregido_a_otro():
    records = [{**SAMPLE_ROW_VALID, "vin": "V002", "grupo": ""}]
    normalized, invalids = normalize_grupo(records)
    assert normalized[0]["grupo"] == "Otro"
    assert invalids == [("V002", "")]


def test_normalize_grupo_no_muta_original():
    record = {**SAMPLE_ROW_VALID, "vin": "V003", "grupo": "Ciudad"}
    original_grupo = record["grupo"]
    normalize_grupo([record])
    assert record["grupo"] == original_grupo  # no mutar el original


def test_normalize_grupo_mixed():
    records = [
        {**SAMPLE_ROW_VALID, "vin": "A", "grupo": "Mexicali"},
        {**SAMPLE_ROW_VALID, "vin": "B", "grupo": "BadGroup"},
        {**SAMPLE_ROW_VALID, "vin": "C", "grupo": "Tijuana"},
        {**SAMPLE_ROW_VALID, "vin": "D", "grupo": "Unknown"},
    ]
    normalized, invalids = normalize_grupo(records)
    assert normalized[0]["grupo"] == "Mexicali"
    assert normalized[1]["grupo"] == "Otro"
    assert normalized[2]["grupo"] == "Tijuana"
    assert normalized[3]["grupo"] == "Otro"
    assert invalids == [("B", "BadGroup"), ("D", "Unknown")]


def test_normalize_grupo_empty_list():
    normalized, invalids = normalize_grupo([])
    assert normalized == []
    assert invalids == []
