import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ChatMessage, parseQuotedReply } from '../src/pages/events/ChatMessage';

/** 全部使用虚构聊天，验证拆分不会丢失回复或冒充可跳转的消息关联。 */
const quote = '虚构报告导出失败。\n第二行补充错误现象。';
const body = '虚构回复：已收到，明天继续排查。';
const source = '虚构测试讨论组';
const content = `"虚构同事:\n${quote} "\n------\n${body}\n> 引用：${source}`;

test('完整回复格式保留正文、旧话与来源，支持多行及 CRLF', () => {
  const expected = { author: '虚构同事', quote, body, source };
  expect(parseQuotedReply(content)).toEqual(expected);
  expect(parseQuotedReply(content.replaceAll('\n', '\r\n'))).toEqual(expected);
});

test('中文成对引号及省略来源仍识别，保留多行回复的最后一行', () => {
  const withoutSource = content.slice(0, content.indexOf('\n> 引用'));
  const curly = `“虚构同事：\n${quote}\n”\n------\n${body}\n虚构最后一行补充。`;
  expect(parseQuotedReply(withoutSource)).toEqual({
    author: '虚构同事',
    quote,
    body,
    source: null,
  });
  const expected = {
    author: '虚构同事',
    quote,
    body: `${body}\n虚构最后一行补充。`,
    source: null,
  };
  expect(parseQuotedReply(curly)).toEqual(expected);
  expect(parseQuotedReply(`${curly}\n> 引用：${source}`)).toEqual({
    ...expected,
    source,
  });
  const markup = renderToStaticMarkup(
    createElement(ChatMessage, { content: curly, excerpt: curly }),
  );
  expect(markup).toContain('class="chat-quote"');
  expect(markup).toContain('虚构最后一行补充。');
  expect(markup).not.toContain('class="chat-quote-source"');
});

test('缺字段、截断、普通横线及嵌套格式不猜测拆分', () => {
  for (const value of [
    '虚构正文\n------\n另一段正文',
    content.slice(0, content.indexOf(body)),
    content.replace(' "\n------', '\n------'),
    content.replace(body, ''),
    content.replace(quote, ''),
    content.replace(source, ''),
    content.replace(quote, '虚构嵌套内容\n------\n另一段'),
    content.replace(/^"/, '“'),
    content.replace(' "\n------', ' ”\n------'),
  ]) {
    expect(parseQuotedReply(value)).toBeNull();
  }
});

test('缺少完整证据版本时仍展示原摘要，普通消息继续保留全文入口', () => {
  const missing = renderToStaticMarkup(
    createElement(ChatMessage, { excerpt: content, content: null }),
  );
  expect(missing).not.toContain('class="chat-quote"');
  expect(missing).toContain('&gt; 引用');
  const plain = renderToStaticMarkup(
    createElement(ChatMessage, {
      excerpt: '虚构消息开头',
      content: '虚构消息开头，以及后续补充。',
    }),
  );
  expect(plain).toContain('展开全文');
  expect(plain).toContain('以及后续补充。');
});

test('合成浏览器：正文气泡与灰色引用分离，展开可读完整旧话和来源', async ({
  page,
}) => {
  // 使用本项目样式与真实组件的静态输出；原生 details 交互不需要另起服务。
  const css = readFileSync('tailwind.css', 'utf8').replace(
    /^@import[^;]+;/gm,
    '',
  );
  const longQuote = `${quote}\n${'虚构很长的引用内容。'.repeat(45)}\n<img src=x onerror=alert(1)>`;
  const markup = renderToStaticMarkup(
    createElement(ChatMessage, {
      excerpt: content.slice(0, 12),
      content: content.replace(quote, longQuote),
    }),
  );
  await page.route('**/*', (route) => route.abort());
  await page.setContent(
    `<style>${css}</style><div style="width:420px"><div class="chat-row internal" style="max-width:100%"><div class="chat-message-body">${markup}</div></div></div>`,
  );
  await expect(page.locator('.chat-bubble')).toHaveText(body);
  const reference = page.locator('.chat-quote');
  await expect(reference).not.toHaveAttribute('open', '');
  await expect(reference.locator('.chat-quote-content')).toBeHidden();
  await expect(reference.locator(':scope > summary')).toHaveCSS(
    'border-right-width',
    '2px',
  );
  const preview = await reference
    .locator('.chat-quote-preview')
    .evaluate((el) => ({
      height: el.clientHeight,
      fullHeight: el.scrollHeight,
      lineHeight: Number.parseFloat(getComputedStyle(el).lineHeight),
    }));
  expect(preview.height).toBeLessThanOrEqual(preview.lineHeight * 2 + 1);
  expect(preview.fullHeight).toBeGreaterThan(preview.height);
  await reference.locator(':scope > summary').click();
  await expect(reference.locator('.chat-quote-content p').first()).toHaveText(
    longQuote,
  );
  await expect(reference.locator('.chat-quote-source')).toHaveText(
    `引用来源：${source}`,
  );
  await expect(page.locator('img, a')).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await reference.locator(':scope > summary').press('Enter');
  await expect(reference.locator('.chat-quote-content')).toBeHidden();
});

test('连续引用尾行一起收起，图片不伪装成已读取，保留原始消息', async ({
  page,
}) => {
  const mixed = `"虚构同事:\n[图片]\n"\n------\n${body}\n> 引用：虚构来源\n> 引用：[图片]`;
  expect(parseQuotedReply(mixed)?.body).toBe(body);
  const markup = renderToStaticMarkup(
    createElement(ChatMessage, { content: mixed, excerpt: mixed }),
  );
  await page.setContent(markup);
  await expect(page.locator('.chat-bubble')).toHaveText(body);
  await page.locator('.chat-quote > summary').click();
  await expect(
    page.getByText('仅记录图片标记，未提供图片内容。'),
  ).toBeVisible();
  await page.getByText('查看原始消息', { exact: true }).click();
  await expect(page.locator('.chat-quote-content details p')).toHaveText(mixed);
});

test('仅带引用尾行的普通回复也收起，不把正文中的引用行删除', () => {
  const value = `${body}\n> 引用：虚构来源\n> 引用：[图片]`;
  const markup = renderToStaticMarkup(
    createElement(ChatMessage, { content: value, excerpt: value }),
  );
  expect(markup).toContain('class="chat-quote"');
  expect(
    markup.split('class="chat-bubble"')[1].split('</div>')[0],
  ).not.toContain('&gt; 引用');
  const mid = `${body}\n> 引用：正文讨论\n继续补充正文。`;
  expect(
    renderToStaticMarkup(
      createElement(ChatMessage, { content: mid, excerpt: mid }),
    ),
  ).not.toContain('class="chat-quote"');
});
