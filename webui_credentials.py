"""Open WebUI 키를 서버 주소별 OS 자격 증명 저장소에 보관한다."""
from openwebui_client import base_url

SERVICE = 'QA_runner_K.OpenWebUI'


def _store():
    try:
        import keyring
        return keyring
    except ImportError:
        raise ValueError('API Key 저장에 필요한 keyring을 설치하세요: python -m pip install keyring') from None


def load_key(url):
    account = base_url(url)
    try:
        return _store().get_password(SERVICE, account) or ''
    except Exception:
        raise ValueError('Open WebUI API Key를 OS 자격 증명 저장소에서 불러오지 못했습니다.') from None


def save_key(url, value):
    account = base_url(url)
    store = _store()
    try:
        if value.strip():
            store.set_password(SERVICE, account, value.strip())
        elif store.get_password(SERVICE, account) is not None:
            store.delete_password(SERVICE, account)
    except Exception:
        # 백엔드 오류에 자격 증명이 들어 있을 수 있으므로 원문 오류는 출력하지 않는다.
        raise ValueError('Open WebUI API Key 저장에 실패했습니다. OS 자격 증명 저장소 접근을 확인하세요.') from None
