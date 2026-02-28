"""Semantic model — parses YAML model definitions into a queryable structure."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Source:
    name: str
    path: str
    type: str  # csv, parquet, json


@dataclass
class Column:
    name: str
    type: str
    primary: bool = False


@dataclass
class Entity:
    name: str
    source: str
    columns: dict[str, Column] = field(default_factory=dict)


@dataclass
class Relationship:
    from_field: str  # "orders.customer_id"
    to_field: str  # "customers.customer_id"
    type: str  # many_to_one, one_to_many


@dataclass
class Metric:
    name: str
    display_name: str
    expression: str  # SQL expression like "SUM(orders.price * orders.quantity)"
    format: str = "number"  # number, currency, percent


@dataclass
class Dimension:
    name: str
    display_name: str
    expression: str  # SQL expression like "orders.region"
    requires_join: list[str] = field(default_factory=list)


@dataclass
class SemanticModel:
    name: str
    display_name: str
    sources: dict[str, Source] = field(default_factory=dict)
    entities: dict[str, Entity] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    metrics: dict[str, Metric] = field(default_factory=dict)
    dimensions: dict[str, Dimension] = field(default_factory=dict)


def parse_model(yaml_path: str) -> SemanticModel:
    """Parse a YAML semantic model file."""
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {yaml_path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    model = SemanticModel(
        name=raw["name"],
        display_name=raw.get("display_name", raw["name"]),
    )

    # Parse sources
    for name, src in raw.get("sources", {}).items():
        model.sources[name] = Source(name=name, path=src["path"], type=src["type"])

    # Parse entities
    for name, ent in raw.get("entities", {}).items():
        entity = Entity(name=name, source=ent["source"])
        for col_name, col_def in ent.get("columns", {}).items():
            entity.columns[col_name] = Column(
                name=col_name,
                type=col_def["type"],
                primary=col_def.get("primary", False),
            )
        model.entities[name] = entity

    # Parse relationships
    for rel in raw.get("relationships", []):
        model.relationships.append(
            Relationship(
                from_field=rel["from"],
                to_field=rel["to"],
                type=rel.get("type", "many_to_one"),
            )
        )

    # Parse metrics
    for name, met in raw.get("metrics", {}).items():
        model.metrics[name] = Metric(
            name=name,
            display_name=met["display_name"],
            expression=met["expression"],
            format=met.get("format", "number"),
        )

    # Parse dimensions
    for name, dim in raw.get("dimensions", {}).items():
        model.dimensions[name] = Dimension(
            name=name,
            display_name=dim["display_name"],
            expression=dim["expression"],
            requires_join=dim.get("requires_join", []),
        )

    return model
