import { Link } from 'umi';
import { EmptyState } from '@/components/Feedback';

/** 无效地址提供回到主业务页面的入口。 */
export default function NotFound() {
  return (
    <main className="page">
      <EmptyState
        title="这个页面不存在"
        description="可以回到事件列表继续查看。"
        action={<Link to="/events">返回事件</Link>}
      />
    </main>
  );
}
