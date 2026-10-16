"""AI 스트림의 수신 상태·취소·전체 제한을 UI 스레드와 공유한다."""
import queue
import threading
import time


class RepetitionGuard:
    """한 요청 안에서 긴 연속 반복만 검사한다. 정상 응답의 길이는 제한하지 않는다."""
    def __init__(self):
        self.tail = ''
        self.pending = 0

    def check(self, text):
        self.tail = (self.tail + text)[-4096:]
        self.pending += len(text)
        if self.pending < 32:
            return False
        self.pending = 0
        # 토큰/청크 경계와 무관하게 같은 구절이 연달아 12회 이상,
        # 총 384자 이상 이어진 경우만 중단한다.
        for size in range(4, 161):
            count = max(12, (384 + size - 1) // size)
            if len(self.tail) >= size * count:
                unit = self.tail[-size:]
                if unit.strip() and self.tail.endswith(unit * count):
                    return True
        return False


class OptimizationProgress:
    def __init__(self, total_timeout):
        self.started = time.monotonic()
        self.deadline = self.started + total_timeout
        self.total_timeout = total_timeout
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.state = dict(phase='요청 준비', chars=0, reasoning_chars=0, sources=0,
                          preview='', finish_reason='', request=0)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def append(self, text='', reasoning=''):
        with self.lock:
            self.state['chars'] += len(text)
            self.state['reasoning_chars'] += len(reasoning)
            if text:
                self.state['preview'] = (self.state['preview'] + text)[-8000:]

    def snapshot(self):
        with self.lock:
            return dict(self.state, elapsed=round(time.monotonic()-self.started, 1),
                        total_timeout=self.total_timeout)

    def check(self):
        if self.cancelled.is_set():
            raise ValueError('최적화 요청을 취소했습니다. 입력 내용은 유지됩니다')
        if time.monotonic() >= self.deadline:
            self.update(phase='전체 작업 시간 초과')
            raise ValueError(f'최적화 전체 작업 제한({self.total_timeout}초)을 초과했습니다. '
                             '중간 응답과 수신 상태를 확인하세요. 입력 내용은 유지됩니다')


def response_packets(session, url, payload, idle_timeout, progress, provider='Open WebUI'):
    """읽기 스레드와 분리하여 헤더/본문 대기 중에도 취소·전체 제한을 확인한다."""
    packets = queue.Queue(maxsize=16)
    stopped = threading.Event()
    active = []

    def put(kind, value):
        while not stopped.is_set():
            try:
                packets.put((kind, value), timeout=0.1)
                return
            except queue.Full:
                pass

    def read():
        response = None
        try:
            response = session.request('POST', url, json=payload, stream=True,
                                       timeout=(5, idle_timeout), allow_redirects=False)
            active.append(response)
            if stopped.is_set():
                return
            put('headers', response)
            if not response.ok or 300 <= response.status_code < 400:
                return
            if 'application/json' in response.headers.get('Content-Type', '').lower():
                put('json', response.json())
            else:
                # 작은 SSE 델타도 버퍼가 찰 때까지 기다리지 않고 전달한다.
                for line in response.iter_lines(chunk_size=1):
                    if stopped.is_set():
                        break
                    put('line', line.decode('utf-8') if isinstance(line, bytes) else line)
            put('eof', None)
        except Exception as error:
            put('error', error)
        finally:
            if response is not None:
                try:
                    response.close()
                except (OSError, ValueError):
                    pass

    progress.check()
    threading.Thread(target=read, daemon=True).start()
    last_packet = time.monotonic()
    try:
        while True:
            progress.check()
            if time.monotonic()-last_packet >= idle_timeout:
                raise ValueError(f'{provider} 응답 수신이 {idle_timeout}초 동안 없어 중단했습니다. '
                                 '입력 내용은 유지됩니다')
            try:
                kind, value = packets.get(timeout=0.1)
            except queue.Empty:
                continue
            progress.check()
            last_packet = time.monotonic()
            if kind == 'error':
                # 서버 본문이나 인증 헤더 등은 오류 메시지에 노출하지 않는다.
                raise ValueError(provider + ' 스트림 통신이 중단됐습니다 (' + type(value).__name__ +
                                 '). 수신 상태와 서버 로그를 확인하세요. 입력 내용은 유지됩니다') from None
            yield kind, value
            if kind == 'eof':
                return
    finally:
        stopped.set()
        # requests의 소켓 읽기가 남아 있어도 UI/작업 스레드를 close()로 막지 않는다.
        if active:
            threading.Thread(target=active[0].close, daemon=True).start()
