from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    payload, content_type = request.app.state.metrics.render_metrics()
    return Response(payload, headers={"Content-Type": content_type})
