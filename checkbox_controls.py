"""라벨과 연결된 네이티브/ARIA 체크박스를 찾고 목표 상태로 설정한다."""
import re
import time


class CheckboxControl:
    def __init__(self, page, control, click_target=None):
        self.page = page
        self.control = control
        self.click_target = click_target

    def is_checked(self):
        return self.control.is_checked()

    def set_checked(self, checked, timeout=5000):
        if self.is_checked() == checked:
            return
        if self.control.is_visible():
            self.control.set_checked(checked, timeout=timeout)
        elif self.click_target is not None:
            # 커스텀 UI의 숨겨진 input은 사용자에게 보이는 라벨을 클릭한다.
            self.click_target.click(timeout=timeout)
        else:
            raise ValueError('숨겨진 체크박스의 클릭 대상을 식별하지 못함')
        deadline = time.monotonic() + timeout / 1000
        while self.is_checked() != checked:
            if time.monotonic() >= deadline:
                raise ValueError('체크박스 목표 상태가 반영되지 않음')
            self.page.wait_for_timeout(100)


def find(page, label):
    name = re.compile(r'^\s*' + r'\s*'.join(re.escape(p) for p in label.split()) + r'\s*$')
    for locator in (page.get_by_role('checkbox', name=name), page.get_by_label(name)):
        visible = locator.filter(visible=True)
        if visible.count() == 1:
            return CheckboxControl(page, visible)
    # label 태그/aria-label 없이 input과 텍스트가 같은 작은 컨테이너에 있는 UI.
    texts = page.get_by_text(name, exact=True).filter(visible=True)
    if texts.count() == 1:
        index = texts.evaluate(r'''text => {
          const selector='input[type="checkbox"], [role="checkbox"]';
          const all=[...document.querySelectorAll(selector)];
          const label=text.closest('label');
          if(label && label.control && label.control.matches(selector))return all.indexOf(label.control);
          let container=text;
          for(let depth=0;container && depth<4;depth++,container=container.parentElement) {
            if(container===document.body)break;
            const controls=[...(container.matches(selector)?[container]:[]),...container.querySelectorAll(selector)];
            if(controls.length>1)return -1;
            if(controls.length===1)return all.indexOf(controls[0]);
          }
          return -1;
        }''')
        if index >= 0:
            control = page.locator('input[type="checkbox"], [role="checkbox"]').nth(index)
            return CheckboxControl(page, control, texts)
    raise ValueError('체크박스를 하나로 식별하지 못함: ' + label)
