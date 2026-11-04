/* Local console interactions for concept intake and review. */
const OperationView = (() => {
  const attributes=['종류','도수','용량','가격','맛','포장','컨셉'];
  const reasons = (db, category) => {
    const reference=db.readiness?.[category];
    if(!reference)return `${category}: 재현 기록 없음. 가상 실행 불가. 접수는 저장할 수 있습니다. 기존 방식으로 정량 조사 후보를 고르세요.`;
    if(db.fit_gate.allowed===false||reference.status!=='pass')return `${category}: 지금 가상 실행이 막혀 있습니다. ${db.fit_gate.reason} 경쟁 세트 재현 ${reference.name} ${reference.status==='pass'?'통과':reference.status==='fail'?'미달':'미확인'}. 접수는 저장할 수 있습니다. 기존 방식으로 정량 조사 후보를 고르세요.`;
    return `${category}: 실험의 모집단·모델·질문 방식을 확인한 뒤 실행할 수 있습니다.`;
  };
  function intake(db, go) {
    const categories=[...new Set(db.products.map(p=>p.category).filter(Boolean))];
    $('content').innerHTML=title('콘셉트 접수','콘셉트마다 공통 경쟁 제품을 붙여 비교합니다.')+
      `<div class="grid"><div><section class="card"><label for="cat">범주</label><select id="cat">${categories.map(x=>`<option>${esc(x)}</option>`).join('')}</select>
      <p class="rule warn" id="categoryReadiness"></p><div id="conceptEntries"></div><button id="moreConcept">콘셉트 추가</button>
      <h3>공통 경쟁 제품</h3><label><input id="crossCategory" type="checkbox"> 다른 범주도 보기</label>
      <select id="competitor" aria-label="경쟁 제품"></select><button id="addProduct">경쟁 제품 추가</button><div id="products"></div>
      <button class="primary" id="saveCards" ${db.state.role==='BM'?'':'disabled'}>접수 저장</button></section></div>
      <section class="card"><h2>최근 접수</h2>${db.state.receipts.slice().reverse().map(x=>`<div class="step"><strong>${esc(x.title)}</strong><p>${esc(x.progress||'설정 전')} · 다음 담당 ${esc(x.next_role||'조사 담당')}</p>
      ${db.state.role==='조사 담당'?`<button data-receipt="${esc(x.id)}">이 접수로 실험 설정</button>`:''}</div>`).join('')||empty('접수된 콘셉트가 없습니다.')}</section></div>`;
    let count=0, selectedProducts=[];
    const add = () => {
      if(count===3)return;
      const number=++count;
      $('conceptEntries').insertAdjacentHTML('beforeend',`<fieldset><legend>콘셉트 ${number}</legend><div class="fields">
        ${field('콘셉트 이름',`concept-title-${number}`,'예: 무알코올 라거')}
        ${attributes.map((a,i)=>field(a,`concept-${number}-${i}`)).join('')}</div></fieldset>`);
      $('moreConcept').disabled=count===3;
    };
    const base=p=>`${p.real_name||p.id} · ${p.launch||'시점 미기록'} · ${p.attrs?.용량||'용량 미기록'} · ${p.category}`;
    function products() {
      const category=$('cat').value;
      $('categoryReadiness').textContent=reasons(db,category);
      const available=db.products.filter(p=>$('crossCategory').checked||p.category===category);
      const totals=available.reduce((m,p)=>(m[base(p)]=(m[base(p)]||0)+1,m),{});
      $('competitor').innerHTML=available.map(p=>`<option value="${esc(p.id)}">${esc(base(p)+(totals[base(p)]>1?' · '+p.id.slice(-4)+' ('+p.id+')':''))}</option>`).join('');
      $('products').innerHTML=selectedProducts.map((id,i)=>`<div class="products-item"><span>${esc(base(db.products.find(p=>p.id===id)))}</span><button data-remove="${i}">빼기</button></div>`).join('');
      $('products').querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{selectedProducts.splice(Number(b.dataset.remove),1);products()});
    }
    add();products();$('moreConcept').onclick=add;
    $('cat').onchange=()=>{selectedProducts=[];products()};
    $('crossCategory').onchange=()=>{if(!$('crossCategory').checked)selectedProducts=selectedProducts.filter(id=>db.products.find(p=>p.id===id).category===$('cat').value);products()};
    $('addProduct').onclick=()=>{const id=$('competitor').value;if(!id||selectedProducts.includes(id))return toast('서로 다른 경쟁 제품을 고르세요.');if(selectedProducts.length>=5)return toast('경쟁 제품은 최대 5개입니다.');selectedProducts.push(id);products()};
    $('saveCards').onclick=()=>action('cards',{category:$('cat').value,competitors:selectedProducts,
      concepts:Array.from({length:count},(_,i)=>({title:$(`concept-title-${i+1}`).value,
          attrs:Object.fromEntries(attributes.map((a,k)=>[a,$(`concept-${i+1}-${k}`).value]))}))});
    $('content').querySelectorAll('[data-receipt]').forEach(b=>b.onclick=()=>go(b.dataset.receipt));
  }

  function shortlist(db,d) {
    const r=db.state.receipts.find(x=>x.id===d.receipt_id);
    if(!r)return '';
    const canUse=d.fit_gate?.allowed&&d.concept_choices?.length&&d.verdict.reason!=='실행 모델 불일치';
    const rows=(r.concepts||[{id:'c1',title:r.title}]).map(c=>{
      const existing=(db.state.shortlist||[]).find(x=>x.experiment===d.name&&x.concept_id===c.id);
      return `<div class="step" data-concept="${esc(c.id)}"><h3>${esc(c.title)}</h3>${existing?`<p>${esc(existing.decision)} · ${esc(existing.reason)} · ${esc(existing.basis)} · ${existing.confirmed_by?'확정':'확인 대기'}</p>`:''}
      ${db.state.role==='BM'&&!existing?.confirmed_by?`<label>결정 <select class="candidateDecision"><option>올림</option><option>뺌</option><option>다음으로 미룸</option></select></label>
      <label>이유 <input class="candidateReason"></label><label>근거 <select class="candidateBasis"><option>가상 결과 쓰지 않음(기존 방식)</option><option ${canUse?'':'disabled'}>가상 결과</option></select></label><button data-propose>제안 저장</button>`:''}
      ${db.state.role==='조사 담당'&&existing&&!existing.confirmed_by?'<button data-confirm>확인</button>':''}</div>`;
    }).join('');
    return FitView.card('정량 조사 후보 결정',rows+`<p><a href="/api/shortlist-memo?receipt=${encodeURIComponent(r.id)}" download>정량 조사 의뢰 메모 내려받기</a></p>`);
  }
  function evidence(d) {
    const gate=d.fit_gate;
    const rows=d.reproduction_rows||[];
    const body=gate?`<p>${esc(gate.reason)}</p>${gate.allowed?FitView.table(['콘셉트','1순위 선택률','유효 응답'],
       d.concept_choices.map(x=>[x.title,pct(x.rate),x.valid])):'<p>가상 결과를 정량 조사 후보 근거로 쓸 수 없습니다.</p>'}`:
      `<p>경쟁 세트 ${rows.length}개 중 최하위를 맞힌 곳 ${rows.filter(r=>r.last_match).length}곳 · 기준 4곳 이상</p>`+
      FitView.table(['경쟁 세트','실제 순위','가상 순위','최하위 맞힘','유효 선택'],rows.map(r=>[r.shelf,r.actual,r.virtual,r.last_match?'O':'X',r.valid]));
    return FitView.card('판정 근거',`<p>판정 입력 지문 <code>${esc(d.verdict_fingerprint?.slice(0,12))}</code></p>`+body);
  }
  function bindShortlist(d) {
    document.querySelectorAll('[data-concept]').forEach(row=>{
      const concept=row.dataset.concept;
      const propose=row.querySelector('[data-propose]'),confirm=row.querySelector('[data-confirm]');
      if(propose)propose.onclick=()=>action('shortlist',{name:d.name,concept,decision:row.querySelector('.candidateDecision').value,
        reason:row.querySelector('.candidateReason').value,basis:row.querySelector('.candidateBasis').value});
      if(confirm)confirm.onclick=()=>action('shortlist-confirm',{name:d.name,concept});
    });
  }
  return {intake,shortlist,evidence,bindShortlist};
})();
