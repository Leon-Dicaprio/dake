"""持久化处理任务的提交、列表和进度查询接口。"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ...ingestion.client import validate_uid
from ...jobs.runner import prepare_request
from ..dependencies import AppServices, services
from ..schemas import RunListResponse, RunRequest, RunResponse, RunExecutionsResponse

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
Deps = Annotated[AppServices, Depends(services)]


@router.get("", response_model=RunListResponse, operation_id="list_runs")
def list_runs(deps: Deps, uid: str | None = Query(default=None, max_length=128),
              mode: Literal["official"] | None = None,
              stream: str | None = Query(default=None, min_length=1, max_length=128)):
    """任务列表提供状态与计数，完整周期详情通过单条任务接口读取。"""
    if uid is not None:
        validate_uid(uid)
    if stream is not None and uid is None:
        raise HTTPException(status_code=422, detail="查询分析范围时必须指定客户")
    return deps.runs.list(uid, mode, stream=stream) if stream is not None else deps.runs.list(uid, mode)


@router.post("", response_model=RunResponse, status_code=202, operation_id="create_run")
def create_run(body: RunRequest, deps: Deps):
    """校验工作量后保存任务，处理在后台逐周期执行。"""
    request, total = prepare_request(deps.settings, body.model_dump())
    run = deps.runs.create(request, total)
    deps.runner.notify()
    return run


@router.get("/{run_id}/executions", response_model=RunExecutionsResponse, operation_id="get_run_executions")
def get_run_executions(run_id: UUID, deps: Deps,
                       uid: str = Query(min_length=1, max_length=128),
                       stream: str = Query(min_length=1, max_length=128),
                       window_index: int = Query(ge=0), offset: int = Query(default=0, ge=0)):
    """先核对任务归属，再读取本窗口过程；失败和零事件窗口也能查看。"""
    validate_uid(uid)
    run = deps.runs.get(str(run_id), uid=uid, stream=stream)
    if run is None or window_index >= run['total_windows']:
        raise HTTPException(status_code=404, detail="未找到该客户的处理窗口")
    return deps.queries.run_executions(str(run_id), uid, stream, window_index, offset)


@router.get("/{run_id}", response_model=RunResponse, operation_id="get_run")
def get_run(run_id: UUID, deps: Deps,
            uid: str | None = Query(default=None, max_length=128),
            stream: str | None = Query(default=None, min_length=1, max_length=128)):
    """返回持久化进度、失败原因及已完成周期，刷新页面不会丢失。"""
    if uid is not None:
        validate_uid(uid)
    if stream is not None and uid is None:
        raise HTTPException(status_code=422, detail="查询分析范围时必须指定客户")
    run = (deps.runs.get(str(run_id), uid=uid, stream=stream)
           if uid is not None else deps.runs.get(str(run_id)))
    if run is None:
        raise HTTPException(status_code=404, detail="未找到处理任务")
    if stream is not None:
        # 历史任务可能缺少冻结范围，只返回确实属于当前范围的周期正文。
        run["cycles"] = [cycle for cycle in run["cycles"]
                         if cycle.get("uid") == uid and cycle.get("stream") == stream]
    return run
