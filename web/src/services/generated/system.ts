// @ts-ignore
/* eslint-disable */
import { request } from "@/services/request";

/** Health 确认服务可访问本地数据库，不回传主机、账户或密码。 GET /health */
export async function health(options?: { signal?: AbortSignal }) {
  return request<API.HealthResponse>("/health", {
    method: "GET",
    ...(options || {}),
  });
}
