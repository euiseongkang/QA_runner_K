"""Open WebUI API를 통해 선택한 지식 기반을 검색하는 AI 클라이언트."""
from urllib.parse import urlsplit, quote
import json

import requests
from ai_stream import RepetitionGuard, response_packets


def base_url(value):
    value = str(value).strip().rstrip('/')
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ('http', 'https') or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or any(c.isspace() for c in value)):
            raise ValueError()
        parts.port
    except ValueError:
        raise ValueError('Open WebUI 주소를 http://localhost:8080 형태로 입력하세요') from None
    return value


class OpenWebUIClient:
    def __init__(self, url, api_key, knowledge_ids=()):
        self.url = base_url(url)
        if not api_key.strip():
            raise ValueError('Open WebUI API Key를 입력하세요 (설정 → 계정 → API Keys)')
        self.knowledge_ids = list(dict.fromkeys(x.strip() for x in knowledge_ids if x.strip()))
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers['Authorization'] = 'Bearer ' + api_key.strip()
        self.last_sources = []

    def close(self):
        self.session.close()

    def _request(self, method, path, timeout=10, **kwargs):
        try:
            response = self.session.request(method, self.url + path, timeout=(5, timeout),
                                            allow_redirects=False, **kwargs)
        except requests.Timeout:
            raise ValueError(f'Open WebUI 응답 대기 시간({timeout}초)을 초과했습니다. '
                             '서버와 모델 상태를 확인하세요. 입력 내용은 유지됩니다') from None
        except requests.ConnectionError:
            raise ValueError('Open WebUI에 연결할 수 없습니다. 실행 상태와 주소를 확인하세요') from None
        if response.status_code in (401, 403):
            raise ValueError('Open WebUI 인증/접근 실패. API Key, API Key 허용 설정 및 지식 기반 접근 권한을 확인하세요')
        if not response.ok or 300 <= response.status_code < 400:
            raise ValueError(f'Open WebUI API 오류 (HTTP {response.status_code}). 주소·모델·서버 로그를 확인하세요')
        try:
            data = response.json()
        except ValueError:
            raise ValueError('Open WebUI API가 JSON 응답을 반환하지 않았습니다. 서버 주소를 확인하세요') from None
        if not isinstance(data, dict) or data.get('error'):
            raise ValueError('Open WebUI API 응답 형식 또는 모델 처리 오류. 서버 로그를 확인하세요')
        return data

    def models(self):
        data = self._request('GET', '/api/models')
        if not isinstance(data.get('data'), list):
            raise ValueError('Open WebUI 모델 목록 형식이 올바르지 않습니다')
        models = []
        for item in data['data']:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                continue
            name = item['id']
            capabilities = item.get('capabilities') or (item.get('ollama') or {}).get('capabilities', [])
            if 'embedding' in name.lower() or 'embed' in name.lower() or (
                    isinstance(capabilities, list) and 'embedding' in capabilities and 'completion' not in capabilities):
                continue
            models.append(name)
        return list(dict.fromkeys(models))

    def knowledge(self):
        items, page = [], 1
        while True:
            data = self._request('GET', '/api/v1/knowledge/', params={'page': page})
            batch = data.get('items')
            if not isinstance(batch, list):
                raise ValueError('Open WebUI 지식 기반 목록 형식이 올바르지 않습니다')
            items.extend(x for x in batch if isinstance(x, dict) and isinstance(x.get('id'), str))
            if not batch or len(items) >= data.get('total', len(items)):
                return items
            page += 1
            if page > 100:
                raise ValueError('지식 기반 목록이 너무 많습니다. 지식 기반 ID를 직접 입력하세요')

    def _stream_chat(self, payload, timeout, progress):
        payload['stream'] = True
        progress.update(phase='Open WebUI 검색·응답 대기', finish_reason='',
                        request=progress.snapshot()['request']+1)
        parts, finish, completed = [], None, False
        sources = []
        event_lines = []
        repetition = RepetitionGuard()

        def consume(data):
            nonlocal finish, completed, sources
            if not isinstance(data, dict) or data.get('error') or data.get('type') == 'error':
                raise ValueError('Open WebUI 스트림 응답에 오류가 있습니다. 서버 로그를 확인하세요')
            incoming = data.get('sources')
            if data.get('type') in ('sources', 'citation') and isinstance(data.get('data'), dict):
                incoming = data['data'].get('sources', incoming)
            if isinstance(incoming, list):
                sources.extend(item for item in incoming if item not in sources)
                progress.update(sources=len(sources), phase='지식 검색 근거 수신 · 모델 응답 대기')
            for choice in data.get('choices') or []:
                if choice.get('index', 0) != 0:
                    continue
                delta = choice.get('delta') or choice.get('message') or {}
                text, reasoning = delta.get('content') or '', delta.get('reasoning_content') or ''
                if isinstance(text, str):
                    parts.append(text)
                    progress.append(text, reasoning if isinstance(reasoning, str) else '')
                    if repetition.check(text):
                        progress.update(phase='동일 문구 연속 반복 감지 · 수신 중단')
                        raise ValueError('AI가 동일 문구를 연속 반복하여 최적화 응답 수신을 중단했습니다. '
                                         '중간 응답은 적용하지 않으며 입력 내용은 유지됩니다. '
                                         '서버에서 생성이 계속되는지는 Ollama 로그를 확인하세요')
                progress.update(phase='모델 응답 수신 중')
                if choice.get('finish_reason'):
                    finish = choice['finish_reason']
                    completed = True
                    progress.update(finish_reason=finish, phase='모델 종료 신호 수신')

        def consume_event():
            nonlocal completed
            if not event_lines:
                return
            value = '\n'.join(event_lines)
            event_lines.clear()
            if value.strip() == '[DONE]':
                completed = True
                progress.update(phase='스트림 완료 신호 수신')
            else:
                try:
                    data = json.loads(value)
                except ValueError:
                    raise ValueError('Open WebUI 스트림 JSON 형식이 잘못되었습니다. 입력 내용은 유지됩니다') from None
                consume(data)

        packets = response_packets(self.session, self.url+'/api/chat/completions', payload, timeout, progress)
        try:
            for kind, value in packets:
                if kind == 'headers':
                    if value.status_code in (401,403):
                        raise ValueError('Open WebUI 인증/접근 실패. API Key와 접근 권한을 확인하세요')
                    if not value.ok or 300 <= value.status_code < 400:
                        raise ValueError(f'Open WebUI API 오류 (HTTP {value.status_code})')
                    progress.update(phase='스트림 연결됨 · 검색/생성 결과 대기')
                elif kind == 'json':
                    progress.update(phase='서버가 일괄 JSON으로 응답함')
                    consume(value)
                    # 스트리밍을 무시한 서버의 기존 JSON 응답도 동일한 검증에 전달한다.
                    completed = bool(value.get('choices'))
                elif kind == 'line':
                    if value.startswith('data:'):
                        event_lines.append(value[5:].lstrip(' '))
                    elif not value:
                        consume_event()
                elif kind == 'eof':
                    consume_event()
                if completed:
                    break
        finally:
            packets.close()
            self.last_sources = sources
        if not completed:
            raise ValueError('Open WebUI 스트림이 종료 신호 없이 끊겼습니다. 중간 응답은 적용하지 않습니다')
        if finish not in (None, 'stop', 'length'):
            raise ValueError('Open WebUI가 TC 답변 대신 다른 종료 상태를 반환했습니다: ' + str(finish))
        return {'sources': sources, 'choices': [{'message': {'content': ''.join(parts)}, 'finish_reason':finish}]}

    def chat(self, model, content, max_tokens=None, timeout=600):
        progress = getattr(self, 'progress', None)
        self.last_sources = []
        if not model.strip() or 'embed' in model.lower():
            raise ValueError('Open WebUI 대화용 모델을 선택하세요. 임베딩 모델은 답변 생성에 사용할 수 없습니다')
        if not self.knowledge_ids:
            raise ValueError('Open WebUI에서 참조할 지식 기반을 선택하세요')
        for identity in self.knowledge_ids:
            if progress is not None:
                progress.check()
                progress.update(phase='지식 기반 접근 확인')
            self._request('GET', '/api/v1/knowledge/' + quote(identity, safe=''))
        messages = [{'role': 'user', 'content': content}]
        if getattr(self, 'system_prompt', ''):
            messages.insert(0, {'role': 'system', 'content': self.system_prompt})
        payload = {'model': model, 'messages': messages, 'stream': False,
                   'files': [{'type': 'collection', 'id': x} for x in self.knowledge_ids],
                   'params': {'function_calling': 'legacy', 'temperature': 0,
                              'keep_alive': 0}}
        # 미지정 시 서버·모델의 생성 설정을 사용한다. null도 전송하지 않는다.
        if max_tokens is not None:
            payload['max_tokens'] = max_tokens
        if getattr(self, 'response_schema', None):
            payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'tc_details', 'strict': True, 'schema': self.response_schema}}
        data = (self._stream_chat(payload, timeout, progress) if progress is not None else
                self._request('POST', '/api/chat/completions', timeout=timeout, json=payload))
        self.last_sources = data.get('sources') or []
        try:
            choice = data['choices'][0]
            value = choice['message']['content']
        except (KeyError, IndexError, TypeError):
            raise ValueError('Open WebUI에서 답변을 받지 못했습니다. 모델과 지식 검색 설정을 확인하세요') from None
        if choice.get('finish_reason') == 'length':
            limit = ('프로그램의 고정 출력 한도는 지정하지 않았습니다. '
                     if max_tokens is None else f'요청 출력 한도는 {max_tokens}토큰입니다. ')
            raise ValueError('Open WebUI 답변이 생성 한도에 도달해 잘렸습니다. ' + limit +
                             'Open WebUI 모델의 Max Tokens(num_predict) 및 컨텍스트 설정을 확인하세요. '
                             '입력 내용은 유지됩니다')
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Open WebUI가 빈 답변을 반환했습니다')
        if not self.last_sources:
            raise ValueError('Open WebUI 응답에 검색 근거가 없습니다. 지식 기반 문서 처리와 RAG 검색 설정을 확인하세요')
        return value
