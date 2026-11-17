// @ts-ignore
/* eslint-disable */
import { request } from "@/services/request";

/** List Schedules 仅查询，名单读取失败与暂无客户分别展示。 GET /api/v1/schedules */
export async function listSchedules(options?: { signal?: AbortSignal }) {
  return request<API.ScheduleListResponse>("/api/v1/schedules", {
    method: "GET",
    ...(options || {}),
  });
}

/** Pause Schedule 停止后续排队；已经提交的当前窗口允许完整结束。 POST /api/v1/schedules/${param0}/pause */
export async function pauseSchedule(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.pauseScheduleParams,
  options?: { signal?: AbortSignal }
) {
  const { schedule_id: param0, ...queryParams } = params;
  return request<API.ScheduleListResponse>(
    `/api/v1/schedules/${param0}/pause`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Resume Schedule 显式恢复会重置重试预算；提交不明时先核实原执行。 POST /api/v1/schedules/${param0}/resume */
export async function resumeSchedule(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.resumeScheduleParams,
  options?: { signal?: AbortSignal }
) {
  const { schedule_id: param0, ...queryParams } = params;
  return request<API.ScheduleListResponse>(
    `/api/v1/schedules/${param0}/resume`,
    {
      method: "POST",
      params: { ...queryParams },
      ...(options || {}),
    }
  );
}

/** Start Schedules 冻结最初起点后持续处理，重复调用不会清空已有进度。 POST /api/v1/schedules/start */
export async function startSchedules(
  body: API.ScheduleStartRequest,
  options?: { signal?: AbortSignal }
) {
  return request<API.ScheduleListResponse>("/api/v1/schedules/start", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}
