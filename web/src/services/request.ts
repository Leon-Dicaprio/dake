type RequestOptions = {
  method?: string;
  data?: unknown;
  signal?: AbortSignal;
  headers?: HeadersInit;
  params?: Record<string, unknown>;
};

/** 只向页面传播服务端明确提供的提示，不把完整响应或聊天内容写到控制台。 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** 生成客户端共用的同源请求层，负责超时、取消和错误提示。 */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== undefined && value !== null && value !== '')
      query.set(key, String(value));
  }
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.data !== undefined || options.method?.toUpperCase() === 'POST')
    headers.set('Content-Type', 'application/json');
  const timeout = AbortSignal.timeout(20000);
  const signal = options.signal
    ? AbortSignal.any([options.signal, timeout])
    : timeout;
  let response: Response;
  try {
    response = await fetch(`${path}${query.size ? `?${query}` : ''}`, {
      method: options.method,
      headers,
      signal,
      body:
        options.data === undefined ? undefined : JSON.stringify(options.data),
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new ApiError(
      0,
      timeout.aborted
        ? '读取时间较长，请重试。'
        : '暂时无法连接本地服务，请确认服务已启动。',
    );
  }
  if (!response.ok) {
    const body = response.headers
      .get('content-type')
      ?.includes('application/json')
      ? ((await response.json()) as { message?: string; detail?: unknown })
      : undefined;
    const message =
      body?.message ||
      (typeof body?.detail === 'string' ? body.detail : undefined);
    throw new ApiError(
      response.status,
      message ||
        (response.status === 422
          ? '填写的信息有误，请检查客户、日期和处理周期。'
          : `读取未完成，请重试（${response.status}）。`),
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
