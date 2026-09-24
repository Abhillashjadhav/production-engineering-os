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


def status_default(entity: Entity) -> str | None:
    """Declared default of the status field, or None when absent/undefaulted."""
    for field in entity.fields:
        if field.name == "status":
            return field.default
    return None


def auth_probe(spec: MvpSpec) -> tuple[str, str] | None:
    """A (method, path) that is auth-guarded in the generated API.

    The negative auth check (expect 401 without a token) must hit a route that
    actually exists — probing GET on the collection when the entity has no
    entity.list capability would get a 404 and wrongly fail the check.
    """
    if not has_auth(spec):
        return None
    for entity in spec.entities:
        caps = capabilities_for(spec, entity)
        route = collection_route(entity)
        if "entity.list" in caps:
            return "GET", route
        if "entity.create" in caps:
            return "POST", route
        if "entity.read" in caps:
            return "GET", route + "/1"
        if "entity.update" in caps:
            return "PATCH", route + "/1"
        if "entity.delete" in caps:
            return "DELETE", route + "/1"
    return None
