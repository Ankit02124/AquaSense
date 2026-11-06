from probes import McuProbes
from settings import load_config, merge


def test_merge_keeps_the_rest_of_a_section():
    base = {"species_profiles": {"tilapia": {"ph": {"warn_low": 6.5, "warn_high": 8.5}, "do_mg_l": {"warn_low": 4}}}}
    merge(base, {"species_profiles": {"tilapia": {"ph": {"warn_high": 9.0}}}})
    assert base["species_profiles"]["tilapia"] == {"ph": {"warn_low": 6.5, "warn_high": 9.0}, "do_mg_l": {"warn_low": 4}}


def test_local_file_overrides(tmp_path):
    (tmp_path / "config.yaml").write_text("species: tilapia\nbehaviour: {z: 3.0, min_fish: 3}\n")
    (tmp_path / "config.local.yaml").write_text("behaviour: {z: 2.5}\n")
    cfg = load_config(tmp_path)
    assert cfg["behaviour"] == {"z": 2.5, "min_fish": 3} and cfg["species"] == "tilapia"


class DeadBridge:
    def call(self, name, *args, timeout=None):
        raise TimeoutError("no answer")


def test_mcu_probes_survive_a_dead_bridge():
    p = McuProbes(bridge=DeadBridge())
    assert p.ping() == "not answering"
    assert p.start() is False
    assert p.status()[0] == "ERROR"
    assert p.result() is None
    p.indicator(2)
    p.abort()
