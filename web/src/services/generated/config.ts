// @ts-ignore
/* eslint-disable */
import { request } from "@/services/request";

/** Get Config 读取界面缺省与客户统计，不返回敏感运行配置。 GET /api/v1/config */
export async function getConfig(options?: { signal?: AbortSignal }) {
  return request<API.ConfigResponse>("/api/v1/config", {
    method: "GET",
    ...(options || {}),
  });
}
