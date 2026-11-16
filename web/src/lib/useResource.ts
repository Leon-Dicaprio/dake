import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from './utils';

/** 按查询键隔离结果；页面切换取消请求，轮询不覆盖其他客户的内容。 */
export function useResource<T>(
  key: string | null,
  loader: (signal: AbortSignal) => Promise<T>,
  pollMs = 0,
  keepPolling?: (data: T) => boolean,
) {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const pollingRef = useRef(keepPolling);
  pollingRef.current = keepPolling;
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{
    key: string | null;
    data?: T;
    error?: string;
    loading: boolean;
    revision: number;
  }>({ key, loading: !!key, revision: 0 });
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      setState((previous) => ({
        key,
        revision,
        data: previous.key === key ? previous.data : undefined,
        error: previous.key === key ? previous.error : undefined,
        loading: true,
      }));
      let continuePolling = true;
      try {
        const data = await loaderRef.current(controller.signal);
        continuePolling = pollingRef.current?.(data) ?? true;
        if (!controller.signal.aborted)
          setState({ key, data, loading: false, revision });
      } catch (error) {
        if (!controller.signal.aborted)
          setState((previous) => ({
            key,
            revision,
            data: previous.key === key ? previous.data : undefined,
            error: errorMessage(error),
            loading: false,
          }));
      }
      if (!controller.signal.aborted && pollMs && continuePolling)
        timer = setTimeout(load, pollMs);
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [key, revision, pollMs]);
  return {
    data: state.key === key ? state.data : undefined,
    error: state.key === key ? state.error : undefined,
    loading:
      key !== null &&
      (state.key !== key || state.revision !== revision || state.loading),
    refresh,
  };
}
