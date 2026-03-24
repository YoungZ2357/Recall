from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.dependencies import GeneratorDep
from app.core.schemas import GenerateRequest, GenerateResponse

router = APIRouter()


@router.post("", response_model=GenerateResponse)
async def generate(
    request: GenerateRequest,
    generator: GeneratorDep,
) -> GenerateResponse | StreamingResponse:
    """Generate an LLM answer from retrieved context.

    Set ``stream: true`` in the request body for SSE streaming.
    """
    if request.stream:
        return StreamingResponse(
            generator.generate_stream(
                query=request.query,
                context=request.context,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await generator.generate(
        query=request.query,
        context=request.context,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
    )
