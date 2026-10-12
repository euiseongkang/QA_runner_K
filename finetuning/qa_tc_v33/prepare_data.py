"""검토한 before_after.json에서 MLX 학습 파일을 재생성하고 형식을 확인한다."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEYS = {'precondition', 'steps', 'expected', 'change_required', 'review_reason'}


def main():
    records = json.loads((ROOT / 'before_after.json').read_text(encoding='utf-8'))
    system = (ROOT / 'system_prompt.txt').read_text(encoding='utf-8').strip()
    assert system and records, '프롬프트와 사례가 필요합니다.'
    ids, inputs = set(), set()
    outputs = {split: [] for split in ('train', 'valid', 'test')}
    for record in records:
        assert record['id'] not in ids, '중복 사례 ID'
        ids.add(record['id'])
        before, after = record['before'], record['after']
        assert set(before) == {'precondition', 'steps', 'expected'}
        assert set(after) == KEYS, '정답 JSON 키가 프로그램 형식과 다릅니다.'
        assert type(after['change_required']) is bool
        assert all(isinstance(after[key], str) and len(after[key]) <= 4000 for key in before)
        assert after['steps'].strip() and after['expected'].strip()
        assert isinstance(after['review_reason'], str) and 0 < len(after['review_reason']) <= 300
        assert after['change_required'] == any(before[key] != after[key] for key in before)
        signature = json.dumps(before, sort_keys=True, ensure_ascii=False)
        assert signature not in inputs, '중복 원본 TC: 학습·평가 누출을 확인하세요.'
        inputs.add(signature)
        user = json.dumps({'title': record['title'], 'original_tc': before,
                           'user_requirements_and_evidence': record['context']}, ensure_ascii=False)
        sample = {'messages': [{'role': 'system', 'content': system},
                               {'role': 'user', 'content': user},
                               {'role': 'assistant', 'content': json.dumps(after, ensure_ascii=False)}]}
        outputs[record['split']].append(sample)
    for split, samples in outputs.items():
        assert samples, f'{split} 사례가 없습니다.'
        path = ROOT / f'{split}.jsonl'
        path.write_text(''.join(json.dumps(s, ensure_ascii=False) + '\n' for s in samples), encoding='utf-8')
        # 파일 자체도 JSONL 및 내부 정답 JSON 파싱이 가능한지 검사한다.
        for line in path.read_text(encoding='utf-8').splitlines():
            parsed = json.loads(line)
            json.loads(parsed['messages'][-1]['content'])
        print(f'{path.name}: {len(samples)}건 형식 검사 완료')
    print('형식 검사는 완료했습니다. 정답 내용의 적절성은 별도 검토해야 합니다.')


if __name__ == '__main__':
    main()
