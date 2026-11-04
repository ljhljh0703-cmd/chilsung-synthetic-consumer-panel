(() => {
  const {card,table,esc,fitPage,overview,status,badge}=FitView;
  const routes={overview:'현황',fit:'모집단 정합성',reproduction:'경쟁 세트 재현',sensitivity:'자극물 민감도',
    workflow:'운영 흐름',audit:'판정 기록',limits:'한계와 공개 범위'};
  const fetchData=async name=>{
    const response=await fetch('data/'+name+'.json');
    if(!response.ok)throw new Error('스냅샷을 읽을 수 없습니다.');
    return response.json();
  };
  const renderRepro=x=>card(`${x.title} (${x.name})`,`<p>${badge(x.verdict)} ${esc(x.reason)}</p>`+
    `<p>최하위 적중 ${x.rows.filter(r=>r.last_match).length}/${x.rows.length}곳 · 기준 4곳 이상</p>`+
    table(['경쟁 세트','실제 순위','가상 순위','최하위 적중','유효 선택'],x.rows.map(r=>[r.shelf,r.actual,r.virtual,r.last_match?'O':'X',`${r.valid}/${r.total}`]))+
    `<p><a href="data/${esc(x.name)}.md" download>운영 보고서 내려받기</a></p>`);
  async function render() {
    const id=location.hash.slice(1);
    const page=Object.hasOwn(routes,id)?id:'overview';
    document.querySelector('nav').innerHTML=Object.entries(routes).map(([key,label])=>`<a href="#${key}" ${key===page?'aria-current="page"':''}>${label}</a>`).join('');
    const snapshot=await fetchData('overview'), x=snapshot.data;
    let body='';
    if(page==='overview')body=overview(x.overview);
    if(page==='fit') { const {data}=await fetchData('fit'); body=fitPage(data.fit,data.limits,'https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/main/results/FIT/registered/report.md'); }
    if(page==='reproduction')body=(await Promise.all(['T2','T4'].map(k=>fetchData('experiments/'+k)))).map(v=>renderRepro(v.data)).join('');
    if(page==='sensitivity'){const s=(await fetchData('experiments/T2')).data.sensitivity;body=card('자극물 민감도 · T2↔T3',
      `<p>1순위 변동 ${esc(s.changed)}/${esc(s.total)} · 최대 이동 ${Number(s.max_shift_pp).toFixed(1)}%p</p><p>${esc(s.comparison_basis)}</p>`);}
    if(page==='workflow')body=[['intake','콘셉트 접수','맥주 콘셉트'],['setup','실험 설정','한 명씩 · 보기 순서 섞음'],['runs','실행 현황','대표성 미달 · 실행 막힘'],
      ['checks','자기 점검','경쟁 세트 재현 · 자극물 민감도'],['decision','판정·후보 결정','보류 · 정량 조사 후보 결정'],['survey','소비자 조사·보정','정량 조사 이후 보정']].map(([key,label,example])=>
      card(label,`<figure><img src="workflow/${key}.png" alt="${esc(label)} 운영 화면" loading="lazy"></figure><label>시연 입력 <input readonly value="${esc(example)}"></label>`)).join('');
    if(page==='audit'){const rows=(await fetchData('audit')).data;body=card('판정 기록',table(['시각','처리','역할','구분'],rows.map(r=>[r.time,r.action,r.actor,'시연 기록'])));}
    if(page==='limits'){const {data}=await fetchData('fit');body=card('한계와 공개 범위',
      `<ul>${data.limits.map(t=>`<li>${esc(t)}</li>`).join('')}</ul><p><a href="data/preregistration-FIT.md">사전 등록 보기</a></p><p>공개 범위는 집계 결과와 시연 화면입니다. 응답 원문과 개별 조사 자료는 제외했습니다.</p>`);}
    if((location.hash.slice(1)||'overview')!==id&&Object.hasOwn(routes,location.hash.slice(1)))return;
    document.querySelector('main').innerHTML=status(x.fit,x.gate,x.overview.reproduction)+body;
    document.querySelector('#snapshot').textContent=`스냅샷 ${snapshot.generated_at} · 코드 ${snapshot.commit.slice(0,12)}`;
  }
  function show(){render().catch(error=>document.querySelector('main').textContent=error.message)}
  addEventListener('hashchange',show);show();
})();
