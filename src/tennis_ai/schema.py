"""Offline-only validation against packaged copies of canonical contracts."""

import json
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


@lru_cache(maxsize=1)
def validators():
    schemas = json.loads(files("tennis_ai").joinpath("contract_schemas.json").read_text())
    # Every ref is resolved from this registry; no network retriever is configured.
    registry = Registry().with_resources(
        (name, Resource.from_contents(value)) for name, value in schemas.items()
    )
    return {name: Draft202012Validator(value, registry=registry) for name, value in schemas.items()}


def validate_schema(name, value):
    error = next(validators()[name].iter_errors(value), None)
    if error:
        location = ".".join(map(str, error.absolute_path)) or "root"
        # Do not echo imported values or private paths in validation errors.
        raise ValueError(f"Invalid {name} at {location}: {error.validator} constraint")
