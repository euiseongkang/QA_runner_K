"""Ollama의 키 없는 로컬/사내 서버 API 연결."""
import base64
import json
from urllib.parse import urlsplit

import requests

# 공식 라이브러리의 설치 가능한 태그. 전체 라이브러리가 아닌 TC용 권장 목록이다.
RECOMMENDED = {
    'qwen2.5:1.5b': '★ 경량 우선 권장 · TC 문구·JSON 초안 · 다운로드 약 986MB · 텍스트 전용 · 결과 검토 필요',
    'gemma3:1b': '초경량 대안 · 짧은 문장 정리 · 다운로드 약 815MB · 텍스트 전용 · 복잡한 TC에는 한계',
}
HEAVIER_MODELS = {
    'qwen2.5:7b': '중형 · 다운로드 약 4.7GB · 텍스트 전용 · 경량 기본 권장 대상 아님',
    'qwen2.5:14b': '고사양 · 다운로드 약 9GB · 텍스트 전용 · 메모리 부족/멈춤 우려 · 경량 모델 권장',
    'gemma3:4b': '이미지 지원 · 다운로드 약 3.3GB · 텍스트 정리만 필요하면 1.5B 경량 모델 권장',
    'gemma3:12b': '고사양 · 다운로드 약 8.1GB · 이미지 지원 · 메모리 부족/멈춤 우려 · 경량 모델 권장',
}


def preferred_model(installed, available):
    """설치 여부만으로 큰 모델을 자동 선택하지 않는다."""
    for preferred in RECOMMENDED:
        for name in installed:
            if name == preferred or name.startswith(preferred + '-'):
                return name
        if preferred in available:
            return preferred
    return ''


def available_models():
    """인터넷으로 실제 공식 모델 페이지가 열리는 권장 태그만 제공한다."""
    available = []
    with requests.Session() as session:
        for name in RECOMMENDED:
            try:
                response = session.get('https://ollama.com/library/' + name, timeout=(3, 5))
                if response.status_code == 200:
                    available.append(name)
                response.close()
            except requests.RequestException:
                pass
    return available


def recommendation(model):
    if model in RECOMMENDED:
        return RECOMMENDED[model]
    for prefix, description in {**RECOMMENDED, **HEAVIER_MODELS}.items():
        if model == prefix or model.startswith(prefix + '-'):
            return description
    if model.endswith(':cloud'):
        return '클라우드 실행 · Ollama 로그인과 인터넷 필요 · 외부 서버에서 처리'
    return '설치된 모델 · 실행에 필요한 메모리와 이미지 지원 여부는 모델별로 다릅니다'


def base_url(mode='local', host='127.0.0.1', port='11434'):
    if mode == 'local':
        return 'http://127.0.0.1:11434'
    try:
        number = int(port)
        if not 1 <= number <= 65535:
            raise ValueError()
        value = str(host).strip().rstrip('/')
        parsed = urlsplit(value if '://' in value else 'http://' + value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.path or parsed.query
                or parsed.fragment or parsed.port is not None):
            raise ValueError()
        hostname = parsed.hostname
        if any(c.isspace() for c in hostname):
            raise ValueError()
        if ':' in hostname:
            hostname = '[' + hostname + ']'
        return f'{parsed.scheme}://{hostname}:{number}'
    except (TypeError, ValueError):
        raise ValueError('Ollama IP/호스트와 포트(1~65535)를 별도로 입력하세요') from None


class OllamaClient:
    def __init__(self, url):
        self.url = url.rstrip('/')
        self.session = requests.Session()
        self.session.trust_env = False

    def close(self):
        self.session.close()

    def _request(self, method, path, timeout=5, **kwargs):
        try:
            response = self.session.request(method, self.url + path,
                                            timeout=(3, timeout), **kwargs)
            data = response.json()
            if not response.ok or (isinstance(data, dict) and data.get('error')):
                raise ValueError('Ollama: ' + str(data.get('error') or f'HTTP {response.status_code}')[:250])
            if not isinstance(data, dict):
                raise ValueError('Ollama API 응답 형식이 올바르지 않습니다')
            return data
        except requests.ConnectionError:
            raise ValueError('Ollama에 연결할 수 없습니다. 실행 상태와 IP·포트를 확인하세요') from None
        except requests.Timeout:
            raise ValueError('Ollama 응답 시간이 초과되었습니다') from None
        except requests.exceptions.JSONDecodeError:
            raise ValueError('Ollama API가 아닌 응답입니다. IP·포트를 확인하세요') from None

    def models(self):
        data = self._request('GET', '/api/tags')
        if not isinstance(data.get('models'), list):
            raise ValueError('Ollama 모델 목록 응답이 올바르지 않습니다')
        return list(dict.fromkeys(item['name'] for item in data['models']
                                 if isinstance(item, dict) and isinstance(item.get('name'), str)))

    def pull(self, model, progress):
        """선택한 Ollama 서버에 모델을 설치하고 서버의 진행률을 전달한다."""
        success = False
        with self.session.post(self.url + '/api/pull', json={'model': model, 'stream': True},
                               timeout=(3, 120)) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get('error'):
                    raise ValueError('모델 설치 실패: ' + str(data['error'])[:250])
                status = str(data.get('status', '설치 중'))
                if data.get('total'):
                    status += f" {min(100, int(data.get('completed', 0) * 100 / data['total']))}%"
                progress(status)
                success = data.get('status') == 'success'
        if not success:
            raise ValueError('모델 설치가 완료되지 않았습니다. 인터넷 연결과 디스크 공간을 확인하세요')

    def chat(self, model, content, max_tokens, timeout=None):
        if not model.strip():
            raise ValueError('Ollama 모델을 선택하세요. 먼저 Ollama에서 모델을 설치해야 합니다')
        message = {'role': 'user', 'content': ''}
        if isinstance(content, str):
            message['content'] = content
        else:
            texts, images = [], []
            for block in content:
                if block.get('type') == 'text':
                    texts.append(block['text'])
                elif block.get('type') == 'image_url':
                    url = block['image_url']['url']
                    if not url.startswith('data:image/') or ';base64,' not in url:
                        raise ValueError('Ollama에는 base64 이미지 입력만 지원합니다')
                    value = url.split(';base64,', 1)[1]
                    base64.b64decode(value, validate=True)
                    images.append(value)
            message['content'] = '\n'.join(texts)
            if images:
                info = self._request('POST', '/api/show', json={'model': model})
                capabilities = info.get('capabilities')
                if isinstance(capabilities, list) and 'vision' not in capabilities:
                    raise ValueError('선택한 Ollama 모델은 이미지 입력을 지원하지 않습니다. 스크린샷 판정에는 gemma3 등 이미지 지원 모델을 선택하세요')
                message['images'] = images
        messages = [message]
        if getattr(self, 'system_prompt', None):
            messages.insert(0, {'role': 'system', 'content': self.system_prompt})
        payload = {'model': model, 'messages': messages, 'stream': False, 'keep_alive': 0,
                   'options': {'num_predict': max_tokens, 'num_ctx': getattr(self, 'context_size', 4096)}}
        schema = getattr(self, 'response_schema', None)
        if schema is not None and not model.endswith(':cloud'):
            payload['format'] = schema
            payload['options']['temperature'] = 0
        data = self._request('POST', '/api/chat', timeout=timeout or 120, json=payload)
        if schema is not None and data.get('done_reason') == 'length':
            # 한도 직전에 완전한 JSON이 끝났다면 버리지 않는다. 내용 검증은 호출자가 수행한다.
            def complete_json(response):
                try:
                    return isinstance(json.loads(response.get('message', {}).get('content', '')), dict)
                except (ValueError, TypeError):
                    return False
            if not complete_json(data):
                # 최적화 요청만 한 번 재시도한다. 모델/컨텍스트 크기와 메모리 상한은 유지한다.
                payload['options']['num_predict'] = min(4096, max_tokens * 2)
                payload['messages'] = messages[:-1] + [{'role': 'user', 'content': message['content'] +
                    '\n출력이 길어지지 않도록 반복을 제거하고 세 항목만 간결한 JSON으로 반환하세요.'}]
                data = self._request('POST', '/api/chat', timeout=timeout or 120, json=payload)
                if data.get('done_reason') == 'length' and not complete_json(data):
                    raise ValueError('출력 한도를 늘려 한 번 재시도했지만 AI 최적화 응답이 다시 잘렸습니다. '
                                     '입력 내용은 유지됩니다. 잠시 후 다시 시도하세요')
        value = data.get('message', {}).get('content')
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Ollama가 빈 답변을 반환했습니다. 모델과 응답 제한을 확인하세요')
        return value
