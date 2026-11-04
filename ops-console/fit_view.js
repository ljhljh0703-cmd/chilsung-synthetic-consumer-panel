/* Shared read-only rendering for local operations and exported snapshots. */
const FitView = (() => {
  const esc = value => String(value ?? '미확인').replace(/[&<>"']/g, char => (
    {'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]
  ));
  const state = v => v == null ? '판정 불가' : v ? '통과' : '미달';
  const color = label => ({통과:'good',미달:'bad','판정 불가':'warn','재검증 필요':'warn'}[label] || '');
  const badge = label => `<span class="tag ${color(label)}">${esc(label)}</span>`;
  const n = value => Number.isFinite(value) ? value.toFixed(2) : '미확인';
  const interval = values => values ? values.map(n).join(' ~ ') : '미확인';
  const table = (headers, rows) => `<div class="table-wrap"><table><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const card = (title, html) => `<section class="card"><h2>${esc(title)}</h2>${html}</section>`;
  const status = (fit, gate, repro='확인 필요') => `<div class="fit-strip" aria-label="실행 상태">
      <a href="#fit">모집단 정합성 <strong>${badge(fit.status)}</strong></a>
      <a href="#reproduction" data-reproduction>경쟁 세트 재현(맥주) <strong>${badge(repro)}</strong></a>
      <a href="#fit">신제품 가상 실행 <strong>${badge(gate.allowed===true?'가능':gate.allowed===false?'막힘':'실험별 확인')}</strong></a></div>`;
  const source = (key, metric, verdict) => {
    if (!metric) return '';
    let rows = Object.entries(metric.cells);
    const rank = rows.slice().sort((a,b)=>b[1].pct-a[1].pct).map(([label])=>label);
    return `<details><summary>${key} · ${state(verdict)} · 평균 절대 차이 ${n(metric.mae_pp)}%p · 순위 상관 ${n(metric.rho)}</summary>${
      table(['항목','기관 값 %','가상 평균 %','3회 범위','95% 구간','차이 %p',...(key==='V3'?['가상 순위']:[])],
        rows.map(([label,v])=>[label,n(v.reference_pct),n(v.pct),interval(v.range_pct),interval(v.ci95_pct),n(v.diff_pp),...(key==='V3'?[rank.indexOf(label)+1]:[])]))}</details>`;
  };
  function fitPage(fit, limits=[], link='') {
    const d=fit.data, intro=`<p>${badge(fit.status)} ${esc(fit.reason)}</p>`;
    if (!d) return card('모집단 정합성',intro+`<p>사전 등록 지문 ${esc(fit.prereg_sha256?.slice(0,12))}</p>`);
    const fixture=d.test_fixture?'<p>시험용 요약 · 실제 결과 아님</p>':'';
    const modelRows=d.combos.map(c=>[c.id,c.persona_info,c.model_requested,Object.entries(c.models_returned).map(([k,v])=>k+' '+v+'건').join(', '),c.questionnaire,c.paths.api||0,c.paths.cli||0]);
    const fitRows=Object.entries(d.rq1['3']||{}).map(([key,v],i)=>source(key,v,fit.per_source?.['3']?.[i])).join('');
    const rq2=Object.entries(d.rq2).map(([key,v])=>[key,...['1','2','3'].map(c=>n(v.mae_by_combo[c])),n(v.rep_spread_combo3),fit.contribution?.[key]?'기여 있음':'미확인']);
    const h4=d.h4.within_age_table.map(r=>[r.age,r.drink,n(r.estimate?.early.pct),n(r.estimate?.late.pct),n(r.estimate?.diff_pp)]);
    return card('모집단 정합성',intro+fixture+`<p>사전 등록 ${esc(d.prereg.revision)} · 지문 ${esc(d.prereg.sha256.slice(0,12))} · 공개 기록 시각 ${esc(d.prereg.locked_at)}</p>
      <p>표본 ${d.population.n}명 · 난수 ${d.population.seed} · 표본 지문 ${esc(d.population.sample_sha256.slice(0,12))} · ${esc(d.population.weighting)}</p>
      <p>실행 ${esc(d.run.started_at)} → ${esc(d.run.finished_at)}</p>`+
      table(['조합','제공 정보','요청 모델','반환 모델','문항','API','로그인'],modelRows)+(link?`<p><a href="${esc(link)}">등록 보고서 내려받기</a></p>`:''))+
      card('대표성 (RQ1)',`<p>V1 남·여 각각 10%p 이내. V2·V3 순위 상관 0.8 이상, 평균 절대 차이 10%p 이내. V3 상위 두 주종은 맥주·소주.</p>`+fitRows)+
      card('정보 기여 (RQ2)',`<p>${fit.computed?.rq2?'기여 있음':'기여 미확인'}</p>`+
        table(['자료','없음','나이·성별·지역','전체 서술','반복 변동폭','판정'],rq2)+
        Object.entries(d.rq2).map(([key,v])=>`<div class="fit-bars" aria-label="${esc(key)} 평균 절대 차이"><b>${esc(key)}</b>${['1','2','3'].map(c=>`<meter min="0" max="100" value="${Number(v.mae_by_combo[c])}"></meter>`).join('')}</div>`).join(''))+
      card('판정 안정성 (RQ3)',`<p>${fit.computed?.rq3==null?'판정 불가':fit.computed.rq3?'안정':'불안정'}</p>`+
        table(['조합','전체','V1','V2','V3'],['3','4','5'].map(c=>[c,state(fit.overall?.[c]),...(fit.per_source?.[c]||[null,null,null]).map(state)])))+
      card('세그먼트 방향 (H4)',`<p>${fit.computed?.h4?'지지':'입증 안 됨'} · 세그먼트와 나이 상관 −0.43</p>`+
        table(['연령군','주종','초기 %','후기 %','차이 %p'],h4))+
      card('응답 품질',table(['조합','응답','제외','제외율','95% 이상 쏠림'],d.combos.map(c=>[
        c.id,c.responses,c.excluded,n(c.excluded_rate*100)+'%',c.skew_flags.map(([q,a,k,total])=>`${q} · ${a} ${k}/${total}`).join(' / ')||'없음'])))+
      card('한계',`<ul>${limits.map(t=>`<li>${esc(t)}</li>`).join('')}</ul><details><summary>탐색 분석 · 판정에 쓰지 않음</summary><p>등록된 탐색 결과 ${d.exploratory.length}건</p></details>`);
  }
  function overview(data) {
    return card('이 도구가 막은 것',`<p>가상 결과 보류 ${data.held.length}건 · 실행 차단 ${data.blocks.length}회 · 순위 사용 승인 거절 ${data.rank_rejections}회</p>
      <ul>${data.held.map(x=>`<li>${esc(x.name)} · ${esc(x.reason)}</li>`).join('')}</ul>
      <a href="#audit">기록 보기</a>`)+card('정량 조사로 넘긴 콘셉트',data.shortlist.length?
        table(['콘셉트','결정','근거'],data.shortlist.map(x=>[x.concept,x.decision,x.basis])):'<p>확정된 후보가 없습니다.</p>')+
      card('이 도구의 범위','<ul><li>판매량·점유율 예측 범위 밖</li><li>사람 정량 조사는 별도 진행</li><li>정합성·재현 통과 전 순위 추천 제한</li></ul>')+
      card('최근 기록',table(['시각','처리','역할'],data.recent.map(x=>[x.time,x.action,x.actor])));
  }
  return {esc,badge,table,card,status,fitPage,overview};
})();
