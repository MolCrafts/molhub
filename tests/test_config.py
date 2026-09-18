"""Process home is molhub.config.home_dir."""

from __future__ import annotations

from pathlib import Path

import pytest

from molhub.config import _initial_home_dir, config


class TestConfig:
    @pytest.mark.real_home_default
    def test_default_home_dir_is_user_cache_molhub(self, monkeypatch):
        """With no ``$MOLHUB_HOME``, the root is the user cache.

        The environment is stated rather than assumed: the singleton now reads
        ``$MOLHUB_HOME`` at import, so asserting on it without saying what the
        environment holds would pass or fail on how the suite was launched.
        """
        monkeypatch.delenv("MOLHUB_HOME", raising=False)
        assert _initial_home_dir() == Path.home() / ".cache" / "molhub"

    def test_molhub_home_env_sets_the_initial_root(self, tmp_path: Path, monkeypatch):
        """``$MOLHUB_HOME`` is the knob a job script has.

        Everything molhub caches lands under this root, so on a cluster it must
        be steerable from outside the process. The name was referenced in two
        modules and set by job scripts while nothing read it, which is how a
        19 GiB tarball landed on a full 30 GiB /home (2026-09-18).
        """
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "env-root"))
        assert _initial_home_dir() == tmp_path / "env-root"

    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_molhub_home_is_treated_as_unset(self, value: str, monkeypatch):
        """``MOLHUB_HOME=`` is how a never-assigned variable looks in a script.

        Resolving it to ``Path("")`` would put the cache wherever the process
        happened to start, which is worse than the default.
        """
        monkeypatch.setenv("MOLHUB_HOME", value)
        assert _initial_home_dir() == Path.home() / ".cache" / "molhub"

    def test_molhub_home_expands_a_tilde(self, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", "~/some-cache")
        assert _initial_home_dir() == Path.home() / "some-cache"

    def test_home_dir_is_a_path(self):
        assert isinstance(config.home_dir, Path)

    def test_home_is_not_a_key(self):
        assert "home" not in config

    def test_writable_is_not_a_key(self):
        assert "writable" not in config

    def test_bracket_home_raises_key_error(self):
        with pytest.raises(KeyError):
            config["home"]

    def test_attribute_home_raises_attribute_error(self):
        with pytest.raises(AttributeError, match="home"):
            config.home  # noqa: B018

    def test_assignment_updates_the_singleton(self, tmp_path: Path):
        previous = config.home_dir
        assigned = tmp_path / "assigned"
        try:
            config.home_dir = assigned
            assert config.home_dir == assigned
        finally:
            config.home_dir = previous

    def test_restore_returns_the_previous_path(self, tmp_path: Path):
        previous = config.home_dir
        try:
            config.home_dir = tmp_path / "assigned"
        finally:
            config.home_dir = previous
        assert config.home_dir == previous

    def test_setting_the_env_after_import_does_not_move_the_root(self, tmp_path: Path, monkeypatch):
        """``$MOLHUB_HOME`` is read once, at import — not on every access.

        A process that wants to move the root afterwards assigns to
        ``config.home_dir``, which is what the CLI's ``--home`` does. Re-reading
        the environment on each access would let the two disagree, so a late
        ``setenv`` is deliberately inert.
        """
        previous = config.home_dir
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "env"))
        assert config.home_dir == previous
        assert config.home_dir != tmp_path / "env"

    def test_config_is_a_molcfg_config(self):
        import molcfg

        from molhub.config import MolhubConfig

        assert isinstance(config, molcfg.Config)
        assert isinstance(config, MolhubConfig)

    def test_module_has_no_factory(self):
        with pytest.raises(ImportError):
            from molhub.config import make_cache  # noqa: F401
