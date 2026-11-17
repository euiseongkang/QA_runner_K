"""TC 사전조건의 브라우저 뷰포트를 실행 전에 적용한다."""
import re

DEFAULT_VIEWPORT = {'width': 1920, 'height': 1080}
BROWSER = re.compile(r'브라우저|뷰포트|\bviewport\b', re.I)
SIZE = re.compile(r'(?<![\d.])([+-]?\d+)\s*(?:px)?\s*[x×ｘ]\s*([+-]?\d+)\s*(?:px)?(?![\d.])', re.I)


def requested(precondition):
    sizes = set()
    for clause in re.split(r'[\n;,；]', str(precondition or '')):
        marker = BROWSER.search(clause)
        if marker:
            sizes.update((int(width), int(height)) for width, height in SIZE.findall(clause[marker.end():]))
    if len(sizes) > 1:
        raise ValueError('사전조건에 서로 다른 브라우저 크기가 있습니다. 하나의 가로×세로 크기를 지정하세요.')
    if not sizes:
        return dict(DEFAULT_VIEWPORT), 'default'
    width, height = next(iter(sizes))
    if not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ValueError('브라우저 가로·세로 크기는 각각 1~16384px이어야 합니다.')
    return dict(width=width, height=height), 'precondition'


def apply(page, tc, execution_context=None):
    record = dict(operation='브라우저 뷰포트 적용', status='pending')
    if execution_context is not None:
        execution_context['phase'] = '브라우저 크기 적용'
        execution_context.setdefault('preparation', []).append(record)
    try:
        size, source = requested(tc.get('precondition'))
        record.update(requested=dict(size), source=source)
        if execution_context is not None:
            execution_context.setdefault('environment', {}).update(viewport_requested=dict(size), viewport_source=source)
        if page.viewport_size != size:
            page.set_viewport_size(size)
        actual = page.viewport_size
        record['actual'] = actual
        if execution_context is not None:
            execution_context['environment']['viewport'] = actual
        if actual != size:
            raise ValueError('요청한 브라우저 크기와 실제 뷰포트 크기가 일치하지 않습니다.')
        record['status'] = 'completed'
        return record
    except Exception as exc:
        record.update(status='failed', error=str(exc))
        raise
