"""Stack adapters — everything specific to a generated product's technology.

V1 ships exactly one stack: python-stdlib-crud-api (ADR-003). The test architect
and the implementation agent both consume this package so that generated tests and
generated code always agree on naming; new stacks are added here without touching
the pipeline stages.
"""

from __future__ import annotations

from pmpe.domain.models import Entity, FunctionalRequirement, MvpSpec

SUPPORTED_STACKS = ("python-stdlib",)


def entity_var(entity: Entity) -> str:
    return entity.name.lower()


def table_name(entity: Entity) -> str:
    return entity.name.lower() + "s"


def collection_route(entity: Entity) -> str:
    return "/" + table_name(entity)


def capabilities_for(spec: MvpSpec, entity: Entity) -> set[str]:
    return {
        fr.capability
        for fr in spec.functional_requirements
        if fr.entity == entity.name and fr.capability.startswith("entity.")
    }


def frs_by_capability(spec: MvpSpec, capability: str) -> list[FunctionalRequirement]:
    return [fr for fr in spec.functional_requirements if fr.capability == capability]


def has_auth(spec: MvpSpec) -> bool:
    return bool(frs_by_capability(spec, "auth.bearer_token"))


def has_health(spec: MvpSpec) -> bool:
    return bool(frs_by_capability(spec, "health.check"))


def fr_ids_for_entity(spec: MvpSpec, entity: Entity) -> list[str]:
    return [
        fr.id
        for fr in spec.functional_requirements
        if fr.entity == entity.name and fr.capability.startswith("entity.")
    ]


def fr_id_for(spec: MvpSpec, entity: Entity, capability: str) -> str:
    for fr in spec.functional_requirements:
        if fr.entity == entity.name and fr.capability == capability:
            return fr.id
    return ""
