import { getConfig } from './generated/config';
import { getEventChanges, listEvents } from './generated/events';
import { createRun, getRun, listRuns } from './generated/runs';
import {
  listSchedules,
  pauseSchedule,
  resumeSchedule,
  startSchedules,
} from './generated/schedules';

/** 页面通过生成客户端访问唯一后端契约；这里仅提供稳定、简短的业务入口。 */
export const api = {
  config: (signal?: AbortSignal) => getConfig({ signal }),
  events: (uid: string, stream: string, type: string, signal?: AbortSignal) =>
    listEvents(
      { uid, stream: stream || undefined, type: type || undefined },
      { signal },
    ),
  eventChanges: (
    eventId: string,
    uid: string,
    stream: string,
    offset: number,
    signal?: AbortSignal,
    executionOffset = 0,
    includeDetails = true,
  ) =>
    getEventChanges(
      {
        event_id: eventId,
        uid,
        stream,
        offset,
        execution_offset: executionOffset,
        include_details: includeDetails,
      },
      { signal },
    ),
  scopedRuns: (uid: string, stream: string, signal?: AbortSignal) =>
    listRuns({ uid, stream }, { signal }),
  scopedRun: (
    runId: string,
    uid: string,
    stream: string,
    signal?: AbortSignal,
  ) => getRun({ run_id: runId, uid, stream }, { signal }),
  createRun: (body: API.RunRequest) => createRun(body),
  schedules: (signal?: AbortSignal) => listSchedules({ signal }),
  startSchedules: (start_date: string) => startSchedules({ start_date }),
  pauseSchedule: (schedule_id: string) => pauseSchedule({ schedule_id }),
  resumeSchedule: (schedule_id: string) => resumeSchedule({ schedule_id }),
};
