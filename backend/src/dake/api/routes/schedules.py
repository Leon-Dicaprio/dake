"""定时配置及客户暂停恢复的薄 HTTP 入口，编排逻辑集中在共用业务服务。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import AppServices, services
from ..schemas import ScheduleListResponse, ScheduleStartRequest

router = APIRouter(prefix="/api/v1/schedules", tags=["schedules"])
Deps = Annotated[AppServices, Depends(services)]


@router.get("", response_model=ScheduleListResponse, operation_id="list_schedules")
def list_schedules(deps: Deps):
    """仅查询，名单读取失败与暂无客户分别展示。"""
    return deps.schedules.status()


@router.post("/start", response_model=ScheduleListResponse, operation_id="start_schedules")
def start_schedules(body: ScheduleStartRequest, deps: Deps):
    """冻结最初起点后持续处理，重复调用不会清空已有进度。"""
    try:
        result = deps.schedules.configure(body.start_date)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    deps.runner.notify()
    return result


@router.post("/{schedule_id}/pause", response_model=ScheduleListResponse, operation_id="pause_schedule")
def pause_schedule(schedule_id: UUID, deps: Deps):
    """停止后续排队；已经提交的当前窗口允许完整结束。"""
    return deps.schedules.control_customer(str(schedule_id), "pause")


@router.post("/{schedule_id}/resume", response_model=ScheduleListResponse, operation_id="resume_schedule")
def resume_schedule(schedule_id: UUID, deps: Deps):
    """显式恢复会重置重试预算；提交不明时先核实原执行。"""
    result = deps.schedules.control_customer(str(schedule_id), "resume")
    deps.runner.notify()
    return result
