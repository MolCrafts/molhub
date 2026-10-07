"""The shipped schema must be a real, self-contained JSON Schema.

Its consumers are the registry CI and the future TypeScript client, neither of
which runs molhub's Python parser. So these tests validate it with a generic
validator and assert it enforces what the parser enforces — if the two drift,
a manifest could pass CI and fail at load, or vice versa.

The file shipped in the Python package is generated from `spec/manifest.schema.yaml`
in this repository. The TypeScript package is generated from that same file and
the registry tooling imports its validator. `molhub-registry` contains data only.
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

# The hand-authored source of truth. The copy under src/ is included in wheels
# so installed clients can validate offline.
CONTRACT_SCHEMA = Path(__file__).parents[1] / "spec" / "manifest.schema.yaml"


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
        text = SCHEMA_PATH.read_text(encoding="utf-8")
        assert '$ref: "http' not in text


class TestVendoredSchemaMatchesTheContract:
    """The wheel's offline copy must be byte-identical to the root contract."""

    def test_the_two_copies_are_identical(self):
        vendored = SCHEMA_PATH.read_bytes()
        contract = CONTRACT_SCHEMA.read_bytes()
        assert vendored == contract, (
            f"{SCHEMA_PATH} has drifted from {CONTRACT_SCHEMA}.\n"
            "Edit the contract under spec/, then run `npm run contract:sync`."
        )


class TestSchemaAcceptsValidManifests:
    def test_an_artifact_without_a_digest(self, validator):
        """Platforms that publish no checksum must still be describable.

        The size carries the cross-check on its own; a HEAD request reports
        content-length without downloading the artifact.
        """
        validator.validate(
            {
                "schema_version": 1,
                "kind": "dataset",
                "namespace": "ns",
                "name": "n",
                "version": "1",
                "title": "T",
                "artifacts": [{"role": "main", "filename": "f", "locators": ["x://y"], "size": 19}],
            }
        )

    def test_an_artifact_without_a_size(self, validator):
        """A published digest is a cross-check on its own."""
        validator.validate(
            {
                "schema_version": 1,
                "kind": "dataset",
                "namespace": "ns",
                "name": "n",
                "version": "1",
                "title": "T",
                "artifacts": [
                    {
                        "role": "main",
                        "filename": "f",
                        "locators": ["x://y"],
                        "digest": "md5:" + "0" * 32,
                    }
                ],
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
            "artifacts": [{"role": "main", "filename": "f", "locators": ["x://y"], "size": 19}],
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

    def test_a_zero_size(self, validator, base):
        """Zero is the shape of a failed transfer, not a smaller artifact.

        A size may be an artifact's only cross-check, so `size: 0` would let an
        empty download verify as correct — exactly the 202-with-empty-body
        incident that motivated this whole layer, reintroduced one level up.
        """
        base["artifacts"][0]["size"] = 0
        self._both_reject(validator, base)

    def test_artifact_with_neither_a_digest_nor_a_size(self, validator, base):
        """With neither, a completed transfer has nothing to be checked against.

        Either alone is fine — molhub never computes a digest, and a size is
        answerable from a HEAD request — but an artifact must carry one.
        """
        base["artifacts"] = [{"role": "main", "filename": "f", "locators": ["x://y"]}]
        self._both_reject(validator, base)

    def test_malformed_artifact_format(self, validator, base):
        base["artifacts"][0]["format"] = "Extended XYZ"
        self._both_reject(validator, base)

    def test_media_type_parameters_are_not_manifest_identity(self, validator, base):
        base["artifacts"][0]["media_type"] = "text/csv; charset=utf-8"
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
