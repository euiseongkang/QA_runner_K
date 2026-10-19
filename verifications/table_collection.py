"""열 이름으로 실제 데이터 셀을 수집하는 공통 DOM 기능. 판정 규칙은 포함하지 않는다."""


def read_columns(page, columns, *, identity_headers=('환자명',), aliases=None):
    """columns 순서의 셀 값만 반환한다. 병합된 빈 결과/로딩 행은 데이터로 세지 않는다."""
    return page.evaluate(r'''({columns,identity,aliases}) => {
      const norm=s=>(s||'').replace(/\s/g,'');
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      const all=[...document.querySelectorAll('table,[role="table"],[role="grid"]')].filter(visible);
      const tables=all.filter(t=>!all.some(other=>other!==t&&t.contains(other)))
        .filter(t=>{const hs=[...t.querySelectorAll('th,[role="columnheader"]')].filter(visible).map(h=>norm(h.innerText));
          return identity.every(h=>hs.includes(norm(h)));});
      if(tables.length!==1)return {error:'대상 목록 테이블을 하나로 식별하지 못함',busy:false};
      const table=tables[0],headers=[...table.querySelectorAll('th,[role="columnheader"]')].filter(visible).map(h=>norm(h.innerText));
      const indices=[];
      for(const name of columns){
        const names=[name,...(aliases[name]||[])].map(norm);
        const matches=headers.map((h,i)=>names.includes(h)?i:-1).filter(i=>i>=0);
        if(matches.length!==1)return {error:'대상 열을 하나로 식별하지 못함: '+name,busy:false};
        indices.push(matches[0]);
      }
      const busy=table.matches('[aria-busy="true"]')||[...table.querySelectorAll('[aria-busy="true"],[role="progressbar"]')].some(visible)||
        [...(table.parentElement?.querySelectorAll('[role="progressbar"]')||[])].some(visible);
      const body=table.querySelector('tbody')||table;
      const rows=[...body.querySelectorAll('tr,[role="row"]')].filter(visible)
        .filter(r=>!r.querySelector('th,[role="columnheader"]'))
        .filter(r=>!r.matches('[role="status"],[aria-busy="true"]'))
        .map(r=>[...r.querySelectorAll('td,[role="cell"],[role="gridcell"]')].filter(visible))
        .filter(cs=>cs.length===headers.length&&cs.every(c=>!(c.colSpan>1)&&Number(c.getAttribute('aria-colspan')||1)<=1));
      // 전체 행 텍스트는 반환하지 않는다. 페이지 렌더링 변경을 확인할 지문만 계산한다.
      let hash=2166136261;
      for(const row of rows)for(const c of row){const s=c.innerText+'\u0000';
        for(let i=0;i<s.length;i++)hash=Math.imul(hash^s.charCodeAt(i),16777619);}
      return {busy,columns,rows:rows.map(cs=>indices.map(i=>cs[i].innerText.trim())),
        fingerprint:(hash>>>0).toString(16)+':'+rows.length};
    }''', dict(columns=list(columns), identity=list(identity_headers), aliases=aliases or {}))
