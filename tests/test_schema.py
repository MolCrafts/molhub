"""The shipped schema must be a real, self-contained JSON Schema.

Its consumers are the index CI and the future TypeScript client, neither of
which runs molhub's Python parser. So these tests validate it with a generic
validator and assert it enforces what the parser enforces — if the two drift,
a manifest could pass CI and fail at load, or vice versa.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import molhub
from molhub.manifest import InvalidManifest, Manifest

from .conftest import manifest_yaml

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_PATH = Path(molhub.__file__).parent / "schema" / "manifest.schema.yaml"


@pytest.fixture(scope="module")
def schema():
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema):
    return jsonschema.Draft202012Validator(schema)


class TestSchemaIsWellFormed:
    def test_it_ships_with_the_package(self):
        assert SCHEMA_PATH.is_file()

    def test_it_is_a_valid_json_schema(self, schema):
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_it_is_self_contained(self, schema):
        """No remote $refs — a consumer must be able to use it offline."""
        text = SCHEMA_PATH.read_text()
        assert '$ref: "http' not in text


class TestSchemaAcceptsValidManifests:
    def test_an_artifact_without_a_digest(self, validator):
        """Platforms that publish nothing must still be describable."""
        validator.validate(
            {
                "schema_version": 1,
                "kind": "dataset",
                "namespace": "ns",
                "name": "n",
                "version": "1",
                "title": "T",
                "artifacts": [{"role": "main", "filename": "f", "locators": ["x://y"]}],
            }
        )

    def test_the_reference_manifest(self, validator):
        validator.validate(yaml.safe_load(manifest_yaml()))

    @pytest.mark.parametrize("kind", ["dataset", "model", "plugin"])
    def test_every_kind(self, validator, kind):
        validator.validate(yaml.safe_load(manifest_yaml(kind=kind)))

    def test_optional_blocks_may_be_absent(self, validator):
        minimal = {
            "schema_version": 1,
            "kind": "dataset",
            "namespace": "ns",
            "name": "n",
            "version": "1",
            "title": "T",
            "artifacts": [{"role": "main", "filename": "f", "locators": ["x://y"]}],
        }
        validator.validate(minimal)


class TestSchemaRejectsWhatTheParserRejects:
    """Every case here must fail on both sides, or CI and runtime disagree."""

    @pytest.fixture
    def base(self):
        return yaml.safe_load(manifest_yaml())

    def _both_reject(self, validator, document):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(document)
        with pytest.raises(InvalidManifest):
            Manifest.from_mapping(document)

    def test_malformed_digest(self, validator, base):
        base["artifacts"][0]["digest"] = "not-a-digest"
        self._both_reject(validator, base)

    def test_missing_version(self, validator, base):
        del base["version"]
        self._both_reject(validator, base)

    def test_unknown_kind(self, validator, base):
        base["kind"] = "notebook"
        self._both_reject(validator, base)

    def test_upper_case_namespace(self, validator, base):
        base["namespace"] = "MolCrafts"
        self._both_reject(validator, base)

    def test_empty_locator_list(self, validator, base):
        base["artifacts"][0]["locators"] = []
        self._both_reject(validator, base)

    def test_no_artifacts(self, validator, base):
        base["artifacts"] = []
        self._both_reject(validator, base)

    def test_wrong_schema_version(self, validator, base):
        base["schema_version"] = 99
        self._both_reject(validator, base)


class TestSchemaCatchesWhatTheParserTolerates:
    """The schema is stricter on purpose; CI should reject sloppiness early."""

    @pytest.fixture
    def base(self):
        return yaml.safe_load(manifest_yaml())

    def test_unknown_top_level_key(self, validator, base):
        base["notafield"] = 1
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(base)

    def test_locator_without_a_scheme(self, validator, base):
        base["artifacts"][0]["locators"] = ["/just/a/path"]
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(base)
