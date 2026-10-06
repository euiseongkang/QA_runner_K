"""Open WebUI API를 통해 선택한 지식 기반을 검색하는 AI 클라이언트."""
from urllib.parse import urlsplit, quote

import requests


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
            raise ValueError('Open WebUI 응답 시간이 초과되었습니다. 서버와 모델 상태를 확인하세요') from None
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

    def chat(self, model, content, max_tokens, timeout=180):
        if not model.strip() or 'embed' in model.lower():
            raise ValueError('Open WebUI 대화용 모델을 선택하세요. 임베딩 모델은 답변 생성에 사용할 수 없습니다')
        if not self.knowledge_ids:
            raise ValueError('Open WebUI에서 참조할 지식 기반을 선택하세요')
        for identity in self.knowledge_ids:
            self._request('GET', '/api/v1/knowledge/' + quote(identity, safe=''))
        messages = [{'role': 'user', 'content': content}]
        if getattr(self, 'system_prompt', ''):
            messages.insert(0, {'role': 'system', 'content': self.system_prompt})
        payload = {'model': model, 'messages': messages, 'stream': False,
                   'files': [{'type': 'collection', 'id': x} for x in self.knowledge_ids],
                   'params': {'function_calling': 'legacy', 'temperature': 0,
                              'num_ctx': 8192, 'keep_alive': 0},
                   'max_tokens': max_tokens}
        if getattr(self, 'response_schema', None):
            payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': 'tc_details', 'strict': True, 'schema': self.response_schema}}
        data = self._request('POST', '/api/chat/completions', timeout=timeout, json=payload)
        self.last_sources = data.get('sources') or []
        try:
            choice = data['choices'][0]
            value = choice['message']['content']
        except (KeyError, IndexError, TypeError):
            raise ValueError('Open WebUI에서 답변을 받지 못했습니다. 모델과 지식 검색 설정을 확인하세요') from None
        if choice.get('finish_reason') == 'length':
            raise ValueError('Open WebUI 답변이 출력 한도로 잘렸습니다. 입력 내용은 유지됩니다')
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Open WebUI가 빈 답변을 반환했습니다')
        if not self.last_sources:
            raise ValueError('Open WebUI 응답에 검색 근거가 없습니다. 지식 기반 문서 처리와 RAG 검색 설정을 확인하세요')
        return value
