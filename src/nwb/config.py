import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

CAPABILITIES = {"text", "vision", "image"}
SUITES = ("core", "naihub-v1")


def find_root(start: Path | None = None) -> Path:
    """Locate the repository root: the nearest directory holding bench/tasks.toml."""
    start = (start or Path.cwd()).resolve()
    for p in (start, *start.parents):
        if (p / "bench" / "tasks.toml").is_file():
            return p
    package_root = Path(__file__).resolve().parents[2]
    if (package_root / "bench" / "tasks.toml").is_file():
        return package_root
    raise FileNotFoundError("bench/tasks.toml not found; run nwb from inside the repository")


def _load(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def validate_run_suite(run_dir: Path, suite: str) -> None:
    from nwb.util import read_json

    for track, pattern in (("understanding", "*/*.json"), ("imagegen", "*/*/*.json")):
        for path in (run_dir / track).glob(pattern):
            if read_json(path).get("suite", "core") != suite:
                raise ValueError(f"run {run_dir.name!r} contains another suite; choose a separate run "
                                 "or pass its matching --suite")


@dataclass(frozen=True)
class Animal:
    id: str
    zh: str
    en: str
    default: bool = False
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnderstandingItem:
    id: str
    modality: str
    lang: str
    prompt: str
    checklist: tuple[str, ...]
    images: tuple[Path, ...] = ()
    image_note: str = ""
    animal: Animal | None = None
    answers: dict[str, str] = field(default_factory=dict)
    control_for: str = ""
    state: str = ""
    category: str = ""
    title: str = ""


@dataclass(frozen=True)
class Tier:
    id: str
    prompt: str
    reference: bool = False
    title_zh: str = ""
    title_en: str = ""
    state: str = ""
    reference_image: Path | None = None

    def render(self, animal: Animal) -> str:
        return self.prompt.format(zh=animal.zh, en=animal.en)


@dataclass
class Bench:
    root: Path
    facts: dict[str, str]
    traits: dict[str, str]
    trait_weights: dict[str, float]
    identity: dict[str, str]
    misconceptions: list[str]
    background: list[str]
    failure_modes: dict[str, str]
    items: list[UnderstandingItem]
    tiers: dict[str, Tier]
    animals: dict[str, Animal]
    reference_image: Path
    state_items: list[UnderstandingItem] = field(default_factory=list)
    state_tiers: dict[str, Tier] = field(default_factory=dict)
    state_animals: tuple[str, ...] = ()
    suite: str = "core"
    annotator: str = ""  # model whose annotations are the suite's answer keys, if any

    @property
    def all_items(self) -> list[UnderstandingItem]:
        return self.items + self.state_items

    @property
    def all_tiers(self) -> dict[str, Tier]:
        return self.tiers | self.state_tiers

    def criterion(self, cid: str) -> str:
        for table in (self.facts, self.traits, self.identity):
            if cid in table:
                return table[cid]
        raise KeyError(cid)

    def expected_prompts(self) -> dict[str, str]:
        """The current prompt of every sample the bench defines, keyed like scoring.sample_key."""
        prompts = {f"understanding/{i.id}": i.prompt for i in self.all_items}
        prompts |= {f"imagegen/{t.id}/{a.id}": t.render(a) for t in self.all_tiers.values() for a in self.animals.values()}
        return prompts

    def select_animals(self, spec: str) -> list[Animal]:
        if spec == "default":
            return [a for a in self.animals.values() if a.default]
        if spec == "all":
            return list(self.animals.values())
        return [self.animals[_known(a, self.animals, "animal")] for a in _split(spec)]


def load_bench(root: Path, suite: str = "core") -> Bench:
    if suite not in SUITES:
        raise ValueError(f"unknown suite {suite!r}; choose from: {', '.join(SUITES)}")
    bench_dir = root / "bench"
    rubric = _load(bench_dir / "rubric.toml")
    tasks = _load(bench_dir / "tasks.toml")
    annotator = ""
    if suite != "core":
        extension = _load(bench_dir / suite / "tasks.toml")
        for section in ("understanding", "grounding", "state_transfer"):
            tasks[section] = extension.get(section, {})
        record = extension.get("dataset", {}).get("annotation_record")
        if record:
            with open(bench_dir / record, encoding="utf-8") as f:
                annotator = json.load(f).get("annotator", {}).get("model", "")

    facts = {k: v["text"] for k, v in rubric.get("facts", {}).items()}
    traits = {k: v["text"] for k, v in rubric.get("traits", {}).items()}
    trait_weights = {k: float(v.get("weight", 1)) for k, v in rubric.get("traits", {}).items()}
    identity = {k: v["text"] for k, v in rubric.get("identity", {}).items()}
    ids = [*facts, *traits, *identity]
    if len(ids) != len(set(ids)):
        raise ValueError("rubric.toml: checklist ids must be unique across facts, traits, and identity")

    animals = {
        k: Animal(k, v["zh"], v["en"], v.get("default", False), tuple(v.get("tags", ())))
        for k, v in tasks["animals"].items()
    }

    items = []
    for item_id, spec in tasks["understanding"].items():
        checklist = tuple(spec["checklist"])
        for cid in checklist:
            if cid not in ids:
                raise ValueError(f"tasks.toml: item {item_id} references unknown checklist id {cid!r}")
        if spec["modality"] not in ("text", "vision"):
            raise ValueError(f"tasks.toml: item {item_id} has invalid modality {spec['modality']!r}")
        images = tuple(bench_dir / p for p in spec.get("images", ()))
        for img in images:
            if not img.is_file():
                raise FileNotFoundError(f"tasks.toml: item {item_id} image not found: {img}")
        if spec["modality"] == "vision" and not images:
            raise ValueError(f"tasks.toml: vision item {item_id} lists no images")
        common = dict(modality=spec["modality"], lang=spec["lang"], checklist=checklist,
                      images=images, image_note=spec.get("image_note", ""))
        if "animals" in spec:
            for a in spec["animals"]:
                animal = animals[_known(a, animals, "animal")]
                items.append(UnderstandingItem(id=f"{item_id}.{a}", animal=animal,
                                               prompt=spec["prompt"].format(zh=animal.zh, en=animal.en), **common))
        else:
            items.append(UnderstandingItem(id=item_id, prompt=spec["prompt"], **common))

    # Identical questions across images prevent the question from revealing the answer.
    grounding = tasks.get("grounding", {})
    grounding_prompt = grounding.get("prompt", "")
    labels = grounding.get("labels", {})
    if labels:
        grounding_prompt += "\nAllowed labels: " + json.dumps(labels, ensure_ascii=False)
    for name, spec in grounding.get("cases", {}).items():
        image = bench_dir / spec["image"]
        if not image.is_file():
            raise FileNotFoundError(f"grounding image not found: {image}")
        if spec.get("sha256") and hashlib.sha256(image.read_bytes()).hexdigest() != spec["sha256"]:
            raise ValueError(f"grounding image checksum mismatch: {image}")
        if labels and (set(spec["answers"]) != set(labels) or any(
                value not in labels[key] for key, value in spec["answers"].items())):
            raise ValueError(f"grounding case {name}: answers must match the declared labels")
        item_id = f"grounding.{name}"
        common = dict(lang="en", prompt=grounding_prompt, checklist=(), answers=spec["answers"],
                      category=spec.get("category", ""), title=spec.get("title", ""),
                      image_note=spec.get("image_note", ""))
        items.append(UnderstandingItem(id=item_id, modality="vision", images=(image,), **common))
        items.append(UnderstandingItem(id=f"{item_id}.blind", modality="text", control_for=item_id, **common))

    ig = tasks["imagegen"]
    tiers = {k: Tier(k, v["prompt"], v.get("reference", False), v.get("title_zh", k), v.get("title_en", k))
             for k, v in ig["tiers"].items()}
    reference_image = bench_dir / ig["reference_image"]
    if not reference_image.is_file():
        raise FileNotFoundError(f"reference image not found: {reference_image}")

    states = tasks.get("state_transfer", {})
    state_items, state_tiers = [], {}
    state_animals = tuple(_known(a, animals, "animal") for a in states.get("animals", ()))
    for state, spec in states.get("cases", {}).items():
        image = bench_dir / spec["image"]
        if not image.is_file():
            raise FileNotFoundError(f"state reference not found: {image}")
        item_id = f"states.{state}"
        common = dict(lang="en", prompt=states["extraction_prompt"], checklist=(),
                      answers=spec["answers"], state=state, title=f"{spec['title_zh']} · {spec['title_en']}")
        state_items.append(UnderstandingItem(id=item_id, modality="vision", images=(image,), **common))
        state_items.append(UnderstandingItem(id=f"{item_id}.blind", modality="text", control_for=item_id, **common))
        for condition in ("described", "reference"):
            tier_id = f"state_{state}_{condition}"
            prompt = states[f"{condition}_prompt"].replace("{description}", spec["description"])
            state_tiers[tier_id] = Tier(tier_id, prompt, reference=condition == "reference", state=state,
                                       reference_image=image, title_en=f"{spec['title_en']} · {condition}",
                                       title_zh=f"{spec['title_zh']} · {condition}")

    return Bench(
        root=root, facts=facts, traits=traits, trait_weights=trait_weights, identity=identity,
        misconceptions=list(rubric.get("misconceptions", {}).get("items", [])),
        background=list(rubric.get("background", {}).get("items", [])),
        failure_modes=dict(rubric.get("failure_modes", {})),
        items=items, tiers=tiers, animals=animals, reference_image=reference_image,
        state_items=state_items, state_tiers=state_tiers, state_animals=state_animals,
        suite=suite, annotator=annotator,
    )


@dataclass
class ModelSpec:
    name: str
    backend: str
    vendor: str
    model: str
    can: frozenset[str]
    options: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.options.get("label", self.name)


def model_settings(spec: ModelSpec, root: Path | None = None, *, generate: bool = False) -> tuple[dict, str]:
    """Collection identity, independent of labels, prices, timeouts, and credential values."""
    root = root or find_root()
    opts = spec.options
    effort = opts.get("effort", opts.get("reasoning", "default"))
    source = "none" if effort in ("default", "unexposed") else {
        "codex": "cli-flag", "claude": "cli-flag", "acp": "session-config",
    }.get(spec.backend, "none")
    if opts.get("effort_source") == "model-id":
        source = "model-id"
    command = opts.get("command", [])
    if spec.backend in ("codex", "claude"):
        from nwb.backends import get_backend
        backend = get_backend(spec)
        command = backend.command([], generate) if spec.backend == "codex" else backend.command()
    command = [arg.replace(str(root.resolve()), "${NWB_ROOT}").replace(str(Path.home()), "~")
               for arg in command]
    # Keep the argv template. Hash referenced repository files without storing expanded machine paths.
    files = {}
    for arg in command:
        candidate = Path(arg.replace("${NWB_ROOT}", str(root)))
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            relative = candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        if candidate.is_file():
            files[relative] = hashlib.sha256(candidate.read_bytes()).hexdigest()[:16]
    config = dict(opts.get("config", {}))
    if spec.backend == "acp" and source == "session-config" and opts.get("effort_option"):
        config[opts["effort_option"]] = effort
    settings = {"backend": spec.backend, "model": spec.model, "effort": effort,
                "effort_source": source, "config": config, "command": command, "files": files}
    # Environment values may contain keys or private paths; only their names are retained.
    env_keys = set(opts.get("env", {}))
    for arg in [*command, *opts.get("env", {}).values()]:
        env_keys.update(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", arg))
    if opts.get("api_key_env"):
        env_keys.add(opts["api_key_env"])
    if env_keys:
        settings["env_keys"] = sorted(env_keys)
    if opts.get("auth"):
        settings["auth"] = opts["auth"]
    if opts.get("usage_command"):
        settings["usage_command"] = opts["usage_command"]
    if spec.backend == "openai":
        base = opts.get("base_url")
        if not base and opts.get("cc_switch"):
            from nwb.backends.openai_compat import cc_switch_credentials
            try:
                base, _ = cc_switch_credentials(opts["cc_switch"])
            except RuntimeError:
                pass  # Missing credentials are reported as a per-job backend error.
        settings["endpoint"] = urlsplit(base).hostname if base else None
        if opts.get("cc_switch"):
            settings["cc_switch"] = opts["cc_switch"]
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    return settings, digest


def load_models(root: Path) -> tuple[dict[str, ModelSpec], dict]:
    data = _load(root / "models.toml")
    local_path = root / "models.local.toml"
    if local_path.is_file():
        local = _load(local_path)
        for name, table in local.get("models", {}).items():
            data.setdefault("models", {}).setdefault(name, {}).update(table)
        data.setdefault("defaults", {}).update(local.get("defaults", {}))

    models = {}
    for name, t in data.get("models", {}).items():
        can = frozenset(t.get("can", ()))
        if not can or not can <= CAPABILITIES:
            raise ValueError(f"model {name}: 'can' must be a non-empty subset of {sorted(CAPABILITIES)}")
        models[name] = ModelSpec(name=name, backend=t["backend"], vendor=t.get("vendor", name),
                                 model=t.get("model", ""), can=can, options=t)
    return models, data.get("defaults", {})


def select_models(models: dict[str, ModelSpec], spec: str, need: str) -> list[ModelSpec]:
    selected = [models[_known(n, models, "model")] for n in _split(spec)]
    for m in selected:
        if need not in m.can:
            raise ValueError(f"model {m.name} cannot do {need!r} (can: {', '.join(sorted(m.can))})")
    return selected


def _split(spec: str) -> list[str]:
    return [s.strip() for s in spec.split(",") if s.strip()]


def _known(name: str, table: dict, kind: str) -> str:
    if name not in table:
        raise ValueError(f"unknown {kind} {name!r}; choose from: {', '.join(table)}")
    return name
