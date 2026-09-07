from querybloom.api.models import llm_ui_metadata
from querybloom.sampling_service import SAMPLING_PRESETS, sampling_ui_metadata


REQUIRED_PREPROCESS = {
    "property_limit",
    "max_triples",
    "seed_property",
    "minimize_patterns",
    "rand_offset",
    "use_cache",
    "include_classes",
    "exclude_classes",
    "exclude_properties",
}
REQUIRED_MINE = {
    "k",
    "num_subgraphs",
    "max_subgraphs_per_seed",
    "exact_support",
    "verif_timeout",
    "m",
    "num_attrs",
    "uniform_types",
}


def test_named_notebook_presets_exist():
    assert "custom" in SAMPLING_PRESETS
    assert "dbpedia-notebook" in SAMPLING_PRESETS
    assert "dblp-notebook" in SAMPLING_PRESETS
    assert SAMPLING_PRESETS["dblp-notebook"]["label"] == "DBLP"
    assert SAMPLING_PRESETS["dblp-notebook"]["config"]["endpoint"] == "dblp"
    dblp_mine = SAMPLING_PRESETS["dblp-notebook"]["config"]["mine"]
    assert dblp_mine["num_subgraphs"] == 48
    assert dblp_mine["max_subgraphs_per_seed"] == 4
    assert dblp_mine["m"] == 30
    assert dblp_mine["num_attrs"] == [20, 25]
    assert dblp_mine["k"] == {3: 0.2, 4: 0.5, 5: 0.3}
    assert SAMPLING_PRESETS["dbpedia-notebook"]["config"]["endpoint"] == "dbpedia-qlever"


def test_every_preset_has_ui_shape():
    for preset_id, preset in SAMPLING_PRESETS.items():
        assert "label" in preset, preset_id
        assert "config" in preset, preset_id
        config = preset["config"]
        assert "endpoint" in config, preset_id
        assert "min_support" in config, preset_id
        assert REQUIRED_PREPROCESS <= set(config["preprocess"]), preset_id
        assert REQUIRED_MINE <= set(config["mine"]), preset_id
        num_attrs = config["mine"]["num_attrs"]
        assert isinstance(num_attrs, (list, tuple)) and len(num_attrs) == 2, preset_id


def test_ui_metadata_exposes_backend_presets():
    metadata = sampling_ui_metadata()
    assert metadata["presets"]["dblp-notebook"]["config"]["min_support"] == 10
    metadata["presets"]["dblp-notebook"]["config"]["min_support"] = 999
    assert SAMPLING_PRESETS["dblp-notebook"]["config"]["min_support"] == 10
    for key in (
        "mine.max_subgraphs_per_seed",
        "mine.m",
        "mine.num_attrs",
        "mine.verif_timeout",
        "mine.exact_support",
        "mine.uniform_types",
        "preprocess.rand_offset",
    ):
        assert key in metadata["fields"], key


def test_llm_ui_metadata_exposes_advanced_fields():
    fields = llm_ui_metadata()["fields"]
    for key in (
        "introduce_complexity_step",
        "reword_questions_step",
        "timeout",
        "max_workers",
        "kg_title",
    ):
        assert key in fields, key
