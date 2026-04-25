from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import SessionDep
from app.core.models import TopologyConfig
from app.retrieval.graph import validate
from app.retrieval.registry import list_node_types
from app.retrieval.topology import TopologySpecJSON

router = APIRouter()

_node_types_cache: list[dict] | None = None


@router.get("/node-types")
async def get_node_types() -> list[dict]:
    global _node_types_cache
    if _node_types_cache is not None:
        return _node_types_cache

    result: list[dict] = []
    for info in list_node_types():
        if info.available and info.config_cls is not None:
            config_schema = info.config_cls.model_json_schema()
        else:
            config_schema = None
        result.append({
            "node_type": info.node_type,
            "display_name": info.display_name,
            "node_role": info.node_role,
            "available": info.available,
            "config_schema": config_schema,
        })

    _node_types_cache = result
    return result


@router.post("/validate")
async def validate_topology(spec: TopologySpecJSON) -> dict:
    errors: list[str] = []

    registry = {info.node_type: info for info in list_node_types()}

    try:
        graph_spec = spec.to_graph_spec(registry)
    except ValueError as e:
        return {"valid": False, "errors": [str(e)]}

    try:
        validate(graph_spec)
    except ValueError as e:
        errors.append(str(e))

    return {"valid": len(errors) == 0, "errors": errors}


# ---------------------------------------------------------------------------
# Presets endpoints
# ---------------------------------------------------------------------------


class CreatePresetRequest(BaseModel):
    name: str
    description: str | None = None
    spec: TopologySpecJSON


def _topology_row_to_dict(row: TopologyConfig) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "is_builtin": row.is_builtin,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "spec": TopologySpecJSON.model_validate_json(row.spec_json).model_dump(),
    }


@router.get("/presets")
async def list_presets(session: SessionDep) -> list[dict]:
    result = await session.execute(select(TopologyConfig).order_by(TopologyConfig.id))
    rows = result.scalars().all()
    return [_topology_row_to_dict(row) for row in rows]


@router.post("/presets")
async def create_preset(
    body: CreatePresetRequest,
    session: SessionDep,
) -> dict:
    registry = {info.node_type: info for info in list_node_types()}

    try:
        graph_spec = body.spec.to_graph_spec(registry)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"valid": False, "errors": [str(e)]},
        )

    try:
        validate(graph_spec)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"valid": False, "errors": [str(e)]},
        )

    existing = await session.execute(
        select(TopologyConfig).where(TopologyConfig.name == body.name)
    )
    if existing.scalar_one_or_none() is not None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "TopologyConfigAlreadyExists",
                "message": f"Preset '{body.name}' already exists",
            },
        )

    row = TopologyConfig(
        name=body.name,
        description=body.description,
        spec_json=body.spec.model_dump_json(),
        is_builtin=False,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    return _topology_row_to_dict(row)


@router.delete("/presets/{preset_id}")
async def delete_preset(preset_id: int, session: SessionDep) -> dict:
    row = await session.get(TopologyConfig, preset_id)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "TopologyConfigNotFound",
                "message": f"Preset with id {preset_id} not found",
            },
        )

    if row.is_builtin:
        return JSONResponse(
            status_code=403,
            content={
                "error": "BuiltinTopologyConfig",
                "message": "Built-in topology configs cannot be deleted",
            },
        )

    await session.delete(row)
    await session.commit()

    return {"deleted": True, "id": preset_id}
