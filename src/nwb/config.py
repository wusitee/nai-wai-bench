import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CAPABILITIES = {"text", "vision", "image"}


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


def load_bench(root: Path) -> Bench:
    bench_dir = root / "bench"
    rubric = _load(bench_dir / "rubric.toml")
    tasks = _load(bench_dir / "tasks.toml")

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
    for name, spec in grounding.get("cases", {}).items():
        image = bench_dir / spec["image"]
        if not image.is_file():
            raise FileNotFoundError(f"grounding image not found: {image}")
        item_id = f"grounding.{name}"
        common = dict(lang="en", prompt=grounding["prompt"], checklist=(), answers=spec["answers"])
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
                      answers=spec["answers"], state=state)
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
