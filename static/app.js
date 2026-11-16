/* Farol · modo ao vivo (navegador).
   O navegador NÃO decide nada: veredito, estratégia líder, progresso de formação e avisos chegam prontos
   do servidor (binarias/veredito.py e binarias/avisos.py). Aqui só desenhamos e tocamos o que vier,
   atualizando apenas o que mudou. Tudo fica dentro desta função (sem variáveis globais). */
(() => {
"use strict";

// ================================================================== utilidades
const $ = (id) => document.getElementById(id);
const el = (tag, cls, texto) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto !== undefined) e.textContent = texto;
  return e;
};
const NS = "http://www.w3.org/2000/svg";
const svgUso = (id, cls = "ic") => {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("class", cls); s.setAttribute("aria-hidden", "true");
  const u = document.createElementNS(NS, "use"); u.setAttribute("href", "#" + id); s.appendChild(u);
  return s;
};
const store = {   // localStorage pode não existir (modo privado): a página funciona sem ele
  get(k, padrao) { try { const v = localStorage.getItem(k); return v === null ? padrao : JSON.parse(v); } catch { return padrao; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sem armazenamento: só não lembra */ } },
};
const setTxt = (e, t) => { if (e && e.textContent !== t) e.textContent = t; };
const num = (v, casas = 2) => (v === null || v === undefined ? "—"
  : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }));
const pct = (v, casas = 0) => (v === null || v === undefined ? "—" : num(100 * v, casas) + "%");
const comSinal = (v, casas = 2) => (v > 0 ? "+" : "") + num(v, casas);
const fmtHora = (t) => new Date(t * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
const espera = (ms) => new Promise((r) => setTimeout(r, ms));
const css = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
const FUSO = -new Date().getTimezoneOffset() * 60;   // gráfico em horário local
const ACAO = { CALL: "COMPRA", PUT: "VENDA" };
const SETA = { CALL: "▲", PUT: "▼" };
const ICONE_DIR = { CALL: "i-cima", PUT: "i-baixo" };
const params = new URLSearchParams(location.search);
const DEMO = params.get("demo");
const nomeAtivo = (s) => S.nomes[s] || (s || "").replace(/^frx/, "").replace(/^([A-Z]{3})([A-Z]{3})$/, "$1/$2");

// ================================================================== estado da página e preferências salvas
const S = {
  config: null, ativos: [], nomes: {}, ws: null, conectado: false,
  ativas: new Set(), simbolo: null, tf: "", casas: 5, seg: 60, janelaEntrada: 15,
  fechaEm: null, offset: 0, estados: {}, ranking: null, veredito: null, analise: null,
  limite: 70, lider: null, barras: [], sinais: [], rkAbertos: new Set(), rkAgora: {},
  sid: null, nSid: 0, descartadas: 0, timerCarga: null, carga: null,
  ops: [], opsAba: store.get("opsAba", "ativo"),   // operações de TODOS os contextos, filtradas na tela
};
const P = {
  som: store.get("som", true), volume: store.get("volume", 70), obs: store.get("observacao", false),
  avisarObs: store.get("avisarObs", false), limite: store.get("limite", null),
  todos: store.get("todosSinais.v2", false),   // novo nome: o padrão voltou a ser DESLIGADO
  modo: params.get("modo") || store.get("modo", "simples"),
  letra: params.get("letra") || store.get("letra", "m"),
};

// ================================================================== gráfico (a página funciona mesmo sem ele)
const G = { chart: null, serie: null, assinatura: "", grupos: new Map() };
const TAMANHO_FONTE_GRAFICO = { p: 12, m: 13, g: 14 };
function criarGrafico() {
  try {
    G.chart = LightweightCharts.createChart($("grafico"), {
      autoSize: true,
      layout: { attributionLogo: true, background: { type: "solid", color: css("--grafico-fundo") }, textColor: css("--grafico-texto"),
                fontSize: TAMANHO_FONTE_GRAFICO[P.letra] || 13, fontFamily: css("--fonte-numero") },
      grid: { vertLines: { color: css("--grafico-grade") }, horzLines: { color: css("--grafico-grade") } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.14, bottom: 0.1 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 6, barSpacing: 12 },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal,
                   vertLine: { color: css("--linha-forte"), labelBackgroundColor: css("--superficie-3") },
                   horzLine: { color: css("--linha-forte"), labelBackgroundColor: css("--superficie-3") } },
    });
    G.serie = G.chart.addCandlestickSeries({ upColor: css("--alta"), downColor: css("--baixa"), borderVisible: false,
                                             wickUpColor: css("--alta"), wickDownColor: css("--baixa"), priceLineColor: css("--marca") });
    G.chart.timeScale().subscribeVisibleLogicalRangeChange(posicionarLinhaEntrada);
    G.chart.subscribeCrosshairMove(dicaDoGrafico);
  } catch (e) {
    G.chart = G.serie = null;
    $("vazio").textContent = "Não foi possível carregar o gráfico (sem internet?). O resto da tela continua funcionando.";
  }
}
const barra = (v) => ({ time: v[0] + FUSO, open: v[1], high: v[2], low: v[3], close: v[4] });
function mostrarUltimasVelas() {
  if (!G.chart || !S.barras.length) return;
  const n = S.barras.length, k = innerWidth < 720 ? 45 : 90;   // poucas velas visíveis: o gráfico respira
  G.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - k), to: n + 4 });
}
function atualizarBarra(v) {
  if (!G.serie) return;
  const b = barra(v), ult = S.barras[S.barras.length - 1];
  if (!ult || b.time > ult.time) { S.barras.push(b); G.serie.update(b); }
  else if (b.time === ult.time) { S.barras[S.barras.length - 1] = b; G.serie.update(b); }
  else {   // versão final de uma vela já ultrapassada: o gráfico não aceita update()
    const i = S.barras.findIndex((x) => x.time === b.time);
    if (i >= 0) { S.barras[i] = b; G.serie.setData(S.barras); G.assinatura = ""; desenharMarcadores(); }
  }
}
const idLider = () => S.lider || (S.veredito && S.veredito.comprovada ? S.veredito.estrategia : null);
const porId = (id) => (S.config && S.config.estrategias.find((e) => e.id === id)) || { nome: id, sigla: "?", simples: "", descricao: "" };

/* Marcadores agrupados por vela: uma seta só por vela, com "×N" quando há vários sinais;
   a lista completa aparece ao passar o mouse (dicaDoGrafico). */
function desenharMarcadores() {
  if (!G.serie || !S.config) return;
  const lider = idLider();
  const visiveis = S.sinais.filter((s) => s.principal || s.id === lider || (P.todos && (P.obs || S.ativas.has(s.id))));
  const chave = `${lider}|${P.todos}|${visiveis.length}|${visiveis.length ? visiveis[visiveis.length - 1].t : 0}`;
  if (chave === G.assinatura) return;
  G.assinatura = chave;
  G.grupos = new Map();
  for (const s of visiveis) {
    const t = s.t + FUSO;
    if (!G.grupos.has(t)) G.grupos.set(t, []);
    G.grupos.get(t).push(s);
  }
  const alta = css("--alta"), baixa = css("--baixa"), neutro = css("--texto-3");
  const marcas = [...G.grupos.entries()].sort((a, b) => a[0] - b[0]).map(([t, lista]) => {
    const princ = lista.find((s) => s.principal), daLider = lista.find((s) => s.id === lider), ref = princ || daLider;
    const direcoes = new Set(lista.map((s) => s.dir));
    const dir = ref ? ref.dir : (direcoes.size === 1 ? lista[0].dir : null);
    const texto = (princ ? "★" : "") + (lista.length > 1 ? `×${lista.length}` : "");
    if (!dir) return { time: t, position: "aboveBar", color: neutro, shape: "circle", size: 0.8, text: texto };
    return { time: t, position: dir === "CALL" ? "belowBar" : "aboveBar", color: ref ? (dir === "CALL" ? alta : baixa) : neutro,
             shape: dir === "CALL" ? "arrowUp" : "arrowDown", size: princ ? 1.6 : 1, text: texto };
  });
  G.serie.setMarkers(marcas);
}
function dicaDoGrafico(p) {
  const caixa = $("dicaGrafico");
  if (!p || !p.time || !p.point || !G.grupos.has(p.time)) { caixa.hidden = true; return; }
  const lista = G.grupos.get(p.time), lider = idLider();
  const ul = el("ul");
  for (const s of lista) {
    const e = porId(s.id);
    const li = el("li", s.principal || s.id === lider ? s.dir : "", `${SETA[s.dir]} ${ACAO[s.dir]} · ${e.nome}${s.principal ? " (entrada avisada)" : s.id === lider ? " (líder)" : ""}`);
    ul.appendChild(li);
  }
  caixa.replaceChildren(el("b", "", `${fmtHora(p.time - FUSO)} · ${lista.length} sinal${lista.length > 1 ? "is" : ""}`), ul);
  caixa.hidden = false;
  const area = $("grafico"), w = caixa.offsetWidth, h = caixa.offsetHeight;
  caixa.style.left = `${Math.min(area.clientWidth - w - 8, p.point.x + 14)}px`;
  caixa.style.top = `${Math.max(8, Math.min(area.clientHeight - h - 8, p.point.y - h / 2))}px`;
}
function posicionarLinhaEntrada() {
  const linha = $("linhaEntrada");
  if (!G.chart || !S.barras.length || !S.fechaEm) { linha.hidden = true; return; }
  // logicalToCoordinate só aceita índices inteiros: fim da vela atual = centro dela + meio espaçamento
  const ts = G.chart.timeScale(), n = S.barras.length;
  const xUlt = ts.logicalToCoordinate(n - 1), xAnt = ts.logicalToCoordinate(n - 2);
  const largura = $("grafico").clientWidth - G.chart.priceScale("right").width();
  if (xUlt === null || xAnt === null) { linha.hidden = true; return; }
  const x = xUlt + (xUlt - xAnt) / 2;
  if (x < 0 || x > largura) { linha.hidden = true; return; }
  linha.hidden = false;
  linha.style.left = `${Math.round(x)}px`;
}

// ================================================================== sons
const A = { ctx: null, avisouFalha: false };
function audio() {
  if (!A.ctx) A.ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (A.ctx.state === "suspended") A.ctx.resume();
  return A.ctx;
}
function tom(freq, inicio, dur, tipo = "sine", vol = 0.18) {
  const ctx = audio(), t0 = ctx.currentTime + inicio, alvo = Math.max(0.0002, vol * (P.volume / 100));
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = tipo; o.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(alvo, t0 + 0.012);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g).connect(ctx.destination); o.start(t0); o.stop(t0 + dur + 0.03);
}
function arpejo(base, passo) {
  for (let i = 0; i < 3; i++) tom(base * Math.pow(passo, i), i * 0.13, 0.14, "triangle", 0.2);
  tom(base * Math.pow(passo, 3), 0.42, 0.42, "triangle", 0.2);
}
const SONS = {   // um som por tipo de aviso (os nomes vêm do servidor)
  formando: () => { tom(523, 0, 0.32, "sine", 0.13); tom(659, 0.22, 0.45, "sine", 0.11); },
  entrada_call: () => arpejo(659, 1.19),    // compra: sobe o tom
  entrada_put: () => arpejo(784, 0.84),     // venda: desce o tom
  resultado: () => { tom(880, 0, 0.18, "sine", 0.14); tom(1318, 0.12, 0.5, "sine", 0.1); },
  observacao: () => { tom(330, 0, 0.28, "square", 0.05); tom(294, 0.3, 0.4, "square", 0.045); },
};
function tocar(nome, forcar = false) {
  if ((!P.som && !forcar) || !SONS[nome]) return;
  if (!A.ctx && !forcar) return;   // sem nenhum clique na página o navegador não deixa tocar (liberado no 1º clique)
  try { SONS[nome](); }
  catch (e) {
    if (!A.avisouFalha) { A.avisouFalha = true; toast("Som indisponível", "O navegador não deixou tocar o aviso sonoro.", "erro", "i-alerta"); }
  }
}

// ================================================================== avisos na tela e notificações
function toast(titulo, texto, tipo = "", icone = "i-sino", duracao = 8000) {
  const t = el("div", "aviso " + tipo);
  t.append(svgUso(icone), el("b", "", titulo), el("span", "", texto));
  const caixa = $("toasts");
  caixa.prepend(t);
  setTimeout(() => t.remove(), duracao);
  while (caixa.children.length > 4) caixa.lastChild.remove();
}
function notificar(titulo, texto, forcar = false) {
  if (!("Notification" in window) || Notification.permission !== "granted" || (!document.hidden && !forcar)) return false;
  try {
    new Notification(titulo, { body: texto, tag: "farol", icon: "/static/marca/icone-192.png", badge: "/static/marca/icone-192.png", silent: true });
    return true;
  } catch { return false; }   // alguns navegadores só permitem notificação via service worker
}
const ESTILO_AVISO = { formando: ["prep", "i-ampulheta"], conflito: ["conf", "i-alerta"], lider: ["discreto", "i-sino"],
                       observacao: ["obs", "i-olho"], resultado: ["", "i-check"] };
/* Aviso decidido no servidor (binarias/avisos.py): mostra o texto, toca o som indicado e notifica. */
function mostrarAviso(a, forcar = false) {
  let [tipo, icone] = ESTILO_AVISO[a.categoria] || ["", "i-sino"];
  if (a.categoria === "entrada") { tipo = a.dir; icone = ICONE_DIR[a.dir]; }
  if (a.categoria === "resultado") icone = /LOSS/.test(a.titulo) ? "i-x" : "i-check";
  toast(a.titulo, a.texto, tipo, icone, a.categoria === "lider" ? 6000 : 10000);
  if (DEMO && !forcar) return;   // demonstração: só mostra
  if (a.som) tocar(a.som, forcar);
  if (a.notificar) notificar(a.titulo, a.texto, forcar);
}

// ================================================================== dicas (tooltips "?")
const D = { alvo: null };
function mostrarDica(alvo) {
  const texto = alvo.dataset.dica, dica = $("dica");
  if (!texto) return;
  D.alvo = alvo;
  dica.textContent = texto; dica.hidden = false;
  const r = alvo.getBoundingClientRect(), d = dica.getBoundingClientRect();
  let x = r.left + r.width / 2 - d.width / 2, y = r.bottom + 8;
  if (y + d.height > innerHeight - 8) y = r.top - d.height - 8;
  x = Math.max(8, Math.min(innerWidth - d.width - 8, x));
  dica.style.left = `${x}px`; dica.style.top = `${Math.max(8, y)}px`;
}
function esconderDica() { $("dica").hidden = true; D.alvo = null; }
function ligarDicas() {
  document.addEventListener("mouseover", (e) => {
    const a = e.target.closest("[data-dica]");
    if (a && a !== D.alvo) mostrarDica(a); else if (!a && D.alvo) esconderDica();
  });
  document.addEventListener("focusin", (e) => { const a = e.target.closest("[data-dica]"); if (a) mostrarDica(a); });
  document.addEventListener("focusout", esconderDica);
  document.addEventListener("click", (e) => {
    const a = e.target.closest(".q[data-dica]");
    if (a) { e.preventDefault(); e.stopPropagation(); if (D.alvo === a) esconderDica(); else mostrarDica(a); }
    else if (D.alvo && !e.target.closest("[data-dica]")) esconderDica();
  }, true);
  addEventListener("scroll", esconderDica, { passive: true });
}

// ================================================================== faixa de probabilidade (IC + estimativa + break-even)
const DOMINIO = [0.30, 0.80];
const posicao = (v) => `${Math.max(0, Math.min(100, (100 * (v - DOMINIO[0])) / (DOMINIO[1] - DOMINIO[0])))}%`;
function desenharFaixa(caixa, p, grande = false) {
  if (!caixa._partes) {
    caixa.replaceChildren();
    const partes = { trilho: el("i", "trilho"), ic: el("i", "ic-faixa"), be: el("i", "be"), ponto: el("i", "ponto-est") };
    caixa.append(partes.trilho, partes.ic, partes.be, partes.ponto);
    if (grande) for (const v of [0.4, 0.5, 0.6, 0.7]) { const t = el("span", "eixo", pct(v)); t.style.left = posicao(v); caixa.appendChild(t); }
    caixa._partes = partes;
  }
  const { ic, be, ponto } = caixa._partes;
  const temDados = p && p.acerto !== null && p.acerto !== undefined;
  ic.hidden = ponto.hidden = !temDados;
  if (temDados) {
    ic.style.left = posicao(p.inf);
    ic.style.width = `calc(${posicao(p.sup)} - ${posicao(p.inf)})`;
    ponto.style.left = posicao(p.acerto);
  }
  be.style.left = posicao(p.be);
  if (grande) be.dataset.rotulo = `mínimo p/ lucrar ${pct(p.be, 1)}`;
}

// ================================================================== veredito (cartão grande + barra compacta)
const ICONE_ESTADO = { PREPARANDO: "i-ampulheta", AGUARDAR: "i-pausa", CONFLITO: "i-alerta", OBSERVACAO: "i-olho",
                       INICIO: "i-play", CARREGANDO: "i-ampulheta", ERRO: "i-alerta" };
let assinaturaVeredito = "";
function trocarIcone(caixa, icone) {
  const use = caixa.querySelector("use");
  if (use.getAttribute("href") !== "#" + icone) use.setAttribute("href", "#" + icone);
}
function pilulaDirecao(alvo, v, classeBase) {
  const mostra = v.dir && ["ENTRAR", "PREPARANDO", "OBSERVACAO"].includes(v.estado);
  alvo.hidden = !mostra;
  if (!mostra) return;
  alvo.className = `${classeBase} ${v.dir} ${v.estado === "ENTRAR" ? "" : "contorno"}`;
  alvo.replaceChildren(svgUso(ICONE_DIR[v.dir], ""), document.createTextNode(ACAO[v.dir]));
  alvo.setAttribute("aria-label", `${ACAO[v.dir]}, ${v.dir === "CALL" ? "alta" : "baixa"}`);
}
function mostrarFormacao(v) {
  const p = v.progresso;
  const mostrar = !!p && ["PREPARANDO", "AGUARDAR", "OBSERVACAO"].includes(v.estado);
  $("vFormacao").hidden = !mostrar;
  if (!mostrar) return;
  setTxt($("vFormPct"), `${p.pct}%`);
  let info = `${p.cumpridas} de ${p.total} condições` + (p.dir ? ` · ${ACAO[p.dir]} ${SETA[p.dir]}` : "");
  if (p.cumpridas < p.total) info += p.distancia_atr !== null && p.distancia_atr !== undefined
    ? ` · gatilho a ${num(p.distancia_atr, 2)} ATR` : " · gatilho fora de alcance nesta vela";
  setTxt($("vFormInfo"), `${info} · aviso a partir de ${S.limite}%`);
  const barraF = $("vFormBarra");
  barraF.querySelector(".bf-preench").style.width = `${p.pct}%`;
  const lim = barraF.querySelector(".bf-limite");
  lim.style.left = `${S.limite}%`; lim.title = `aviso a partir de ${S.limite}%`;
  barraF.setAttribute("aria-valuenow", String(p.pct));
  const ul = $("vCondicoes"); ul.replaceChildren();
  for (const c of p.condicoes || []) {
    const li = el("li", c.ok ? "ok" : "", c.texto);
    li.setAttribute("aria-label", `${c.ok ? "Cumprida" : "Ainda não"}: ${c.texto}`);
    ul.appendChild(li);
  }
}
function textoOutras() {
  const alvo = S.veredito && S.veredito.estrategia;
  const partes = [];
  for (const s of Object.values(S.estados)) {
    if (s.id === alvo || !s.dir || !S.ativas.has(s.id)) continue;
    const e = porId(s.id);
    if (s.estado === "SINAL") partes.push(`${e.nome}: sinal agora ${ACAO[s.dir]}`);
    else if (s.estado === "PARCIAL" && s.cumpridas === s.total) partes.push(`${e.nome}: ${ACAO[s.dir]} se a vela fechasse agora`);
    else if (s.estado === "PARCIAL" && s.cumpridas) partes.push(`${e.nome} ${s.cumpridas}/${s.total} ${ACAO[s.dir]}`);
  }
  return partes.length ? `Outras estratégias (sem aviso): ${partes.join(" · ")}` : "";
}
function atualizarOutras() {
  const outras = textoOutras();
  $("vOutras").hidden = !outras; setTxt($("vOutras"), outras);
}
function mostrarVeredito(v) {
  atualizarOutras();   // muda a cada segundo, mesmo com o veredito igual
  const chave = JSON.stringify(v) + S.simbolo + S.tf + S.limite;
  if (chave === assinaturaVeredito) return;
  assinaturaVeredito = chave;
  const card = $("veredito");
  const estadoAntes = card.dataset.estado;
  card.className = `veredito ${v.estado} ${v.estado === "ENTRAR" ? v.dir || "" : ""}`;
  card.dataset.estado = v.estado;
  if (estadoAntes !== v.estado) {   // reinicia a animação de entrada do conteúdo
    const corpo = card.querySelector(".v-corpo"); corpo.style.animation = "none"; void corpo.offsetWidth; corpo.style.animation = "";
  }
  setTxt($("vContexto"), S.simbolo ? `Agora · ${nomeAtivo(S.simbolo)} ${S.tf}` : "Agora");
  const lider = idLider(), chip = $("vLider");
  chip.hidden = !lider;
  if (lider) setTxt(chip, `Líder: ${porId(lider).nome}`);
  const fita = $("vFita"); fita.hidden = !v.rotulo; setTxt(fita, v.rotulo || "");
  trocarIcone($("vIcone"), ICONE_ESTADO[v.estado] || ICONE_DIR[v.dir] || "i-pausa");
  setTxt($("vTitulo"), v.titulo);
  pilulaDirecao($("vDirecao"), v, "v-direcao");
  $("vFrase").textContent = v.frase || "";
  mostrarCarga(v);
  mostrarFormacao(v);
  const p = v.prob;
  $("vProb").hidden = !p;
  if (p) {
    setTxt($("vProbValor"), p.ok ? p.curto : "—");
    setTxt($("vProbFaixa"), p.ok ? p.faixa : "sem dados suficientes");
    setTxt($("vAmostra"), p.amostra);
    setTxt($("vBreakEven"), p.break_even_txt);
    let est = v.nome ? `Estratégia: ${v.nome}` : "";
    if (v.estado === "ENTRAR" && v.concordam && v.concordam.length) est += ` · concordam: ${v.concordam.join(", ")}`;
    setTxt($("vEstrategia"), est);
    desenharFaixa($("vFaixa"), { acerto: p.acerto, inf: p.inf, sup: p.sup, be: p.break_even }, true);
    const av = $("vAvisos"); av.replaceChildren();
    for (const a of p.avisos || []) { const c = el("span", "aviso-chip"); c.append(svgUso("i-alerta"), document.createTextNode(a.texto)); av.appendChild(c); }
  }
  // barra compacta
  const vb = $("vBarra");
  vb.className = `v-barra ${v.estado} ${v.dir || ""}`;
  trocarIcone($("vbIcone"), ICONE_ESTADO[v.estado] || ICONE_DIR[v.dir] || "i-pausa");
  setTxt($("vbTitulo"), v.titulo);
  pilulaDirecao($("vbDir"), v, "vb-dir");
  const info = [];
  if (v.progresso && ["PREPARANDO", "AGUARDAR", "OBSERVACAO"].includes(v.estado)) info.push(`formação ${v.progresso.pct}%`);
  if (p && p.ok) info.push(`prob. estimada ${p.curto} (${p.faixa}, ${p.n} operações)`);
  if (S.simbolo) info.unshift(`${nomeAtivo(S.simbolo)} ${S.tf}`);
  setTxt($("vbInfo"), info.join(" · "));
  atualizarRelogio();
  desenharMarcadores();
}
function vereditoLocal(estado, texto) {
  if (estado === "INICIO") return { estado, titulo: "Escolha um ativo para começar",
    frase: "Toque em Conectar. O Farol analisa o histórico e só sugere entrada quando uma estratégia tem vantagem comprovada." };
  if (estado === "ERRO") return { estado, titulo: "Não foi possível carregar", frase: texto };
  return { estado: "CARREGANDO", titulo: "Analisando o histórico…", carga: S.carga,
    frase: `${nomeAtivo(S.simbolo)} ${S.tf}: carregando as velas e calculando as estratégias.` };
}
/* Etapas do carregamento (mensagens "carga" do servidor): esqueleto + barra + texto. Nunca fica preso:
   o servidor desiste em 30 s e a página também (TEMPO_CARGA), mostrando "Tentar de novo". */
const TEMPO_CARGA = 30000;
function mostrarCarga(v) {
  const caixa = $("vCarga"), carregando = v.estado === "CARREGANDO";
  caixa.hidden = !carregando;
  const acao = $("vAcao");
  acao.hidden = !["INICIO", "ERRO"].includes(v.estado);
  setTxt(acao, v.estado === "ERRO" ? "Tentar de novo" : "Escolher ativo e conectar");
  if (!carregando) return;
  const c = v.carga || { etapa: "velas", texto: "Conectando ao servidor…", feito: 0, total: 1 };
  const frac = c.total ? Math.min(1, (c.feito || 0) / c.total) : 0;
  const total = c.etapa === "estrategias" ? 0.6 + 0.4 * frac : 0.6 * frac;   // velas = 60% da barra
  $("vCargaBarra").querySelector("i").style.width = `${Math.round(100 * total)}%`;
  $("vCargaBarra").setAttribute("aria-valuenow", String(Math.round(100 * total)));
  const detalhe = c.etapa === "velas" && c.total ? ` ${num(c.feito || 0, 0)} de ${num(c.total, 0)}` : "";
  setTxt($("vCargaTxt"), c.texto + detalhe);
  for (const li of $("vCargaEtapas").children) {
    const ordem = { velas: 0, estrategias: 1 }[c.etapa] ?? 0, k = Number(li.dataset.k);
    li.className = k < ordem ? "feita" : k === ordem ? "atual" : "";
  }
}
function aplicarCarga(msg) {
  if (msg.etapa === "erro") { pararTimerCarga(); mostrarVeredito(vereditoLocal("ERRO", msg.texto)); return; }
  S.carga = msg;
  if (!S.veredito || S.veredito.estado === "CARREGANDO") mostrarVeredito(vereditoLocal("CARREGANDO"));
}
function pararTimerCarga() { clearTimeout(S.timerCarga); S.timerCarga = null; }
function aplicarVeredito(v) { if (v) { pararTimerCarga(); S.veredito = v; mostrarVeredito(v); } }
function alturaTopo() { return $("topo").offsetHeight; }
function atualizarBarraCompacta() {
  const r = $("veredito").getBoundingClientRect();
  $("vBarra").hidden = r.bottom > alturaTopo() + 12;
}

// ================================================================== relógio (anel, barra compacta e linha no gráfico)
const CIRC = 2 * Math.PI * 88;
function fmtTempo(s) {
  s = Math.max(0, Math.ceil(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60, p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`;
}
function atualizarRelogio() {
  const anel = $("anel"), prog = $("anelProgresso"), linha = $("linhaEntrada");
  if (!S.conectado || !S.fechaEm) {
    setTxt($("tempo"), "--:--"); setTxt($("tempoRotulo"), "vela fecha em"); setTxt($("vbTempo"), "--:--");
    prog.style.strokeDashoffset = CIRC; linha.hidden = true; return;
  }
  let resta = S.fechaEm - (Date.now() / 1000 + S.offset);
  while (resta < 0) resta += S.seg;
  const estado = S.veredito ? S.veredito.estado : "";
  let tempo = resta, total = S.seg, rotulo = "próxima vela em", chip = `fim da vela · ${fmtTempo(resta)}`;
  if (estado === "ENTRAR") {
    const restaEntrada = S.janelaEntrada - (S.seg - resta);
    if (restaEntrada > 0) { tempo = restaEntrada; total = S.janelaEntrada; rotulo = "para entrar"; chip = `entrada aberta · ${fmtTempo(restaEntrada)}`; }
    else rotulo = "vela fecha em";
  } else if (estado === "PREPARANDO") { rotulo = "confirmação em"; chip = `confirmação · ${fmtTempo(resta)}`; }
  setTxt($("tempo"), fmtTempo(tempo)); setTxt($("tempoRotulo"), rotulo);
  setTxt($("vbTempo"), fmtTempo(tempo)); setTxt($("vbTempoRotulo"), rotulo);
  prog.style.strokeDashoffset = String(CIRC * (1 - tempo / total));
  anel.classList.toggle("urgente", tempo <= Math.min(10, total * 0.25));
  anel.classList.toggle("pulso", estado === "ENTRAR");
  linha.className = "linha-entrada " + (estado === "ENTRAR" ? S.veredito.dir : estado === "PREPARANDO" ? "PREPARANDO" : "");
  setTxt($("linhaEntradaTxt"), chip);
  posicionarLinhaEntrada();
}

// ================================================================== ranking em grupos (ordem honesta vem do servidor)
function statusLinha(l, r) {
  const j = l.janela;
  if (!j || !j.decididas) return 3;
  if (j.vantagem) return 0;
  return j.decididas >= (r.min_ops_amostra || 30) ? 1 : 2;
}
function textoAgora(s) {
  if (!s || !s.dir) return "";
  if (s.estado === "SINAL") return `sinal agora: ${ACAO[s.dir]} ${SETA[s.dir]}`;
  if (s.estado === "FORMANDO") return `se formando: ${ACAO[s.dir]} ${SETA[s.dir]} (${s.pct}%)`;
  if (s.cumpridas && s.cumpridas === s.total) return `${ACAO[s.dir]} se a vela fechasse agora`;
  if (s.cumpridas) return `${s.cumpridas} de ${s.total} condições · ${ACAO[s.dir]}`;
  return "";
}
function stats(rotulo, j, velas) {
  if (!j || !j.decididas) return [rotulo, `nenhuma operação nas últimas ${velas} velas`];
  return [rotulo, `${pct(j.acerto)} (entre ${pct(j.ic_inf)} e ${pct(j.ic_sup)}) · ${j.decididas} operações · últimas ${velas} velas`];
}
function linhaRanking(l, pos, r, lider) {
  const j = l.janela, e = porId(l.id), st = statusLinha(l, r);
  const li = el("li", "rk-item" + (l.id === lider ? " lider" : "") + (S.ativas.has(l.id) ? "" : " desligada") + (S.rkAbertos.has(l.id) ? " aberto" : ""));
  const bt = el("button", "rk-linha"); bt.type = "button";
  bt.setAttribute("aria-expanded", String(S.rkAbertos.has(l.id)));
  const nome = el("span", "rk-nome");
  const ic = el("span", "ic-est"); ic.setAttribute("aria-hidden", "true");
  ic.style.setProperty("--ic-url", `url("/static/icones/${encodeURIComponent(l.id)}.svg")`);
  nome.append(ic, el("span", "", l.nome));
  if (l.id === lider) nome.appendChild(el("span", "badge-lider", "LÍDER"));
  const faixa = el("span", "faixa-prob");
  const pc = el("span", "rk-pct" + (st >= 2 ? " cinza" : ""));
  const info = el("span", "rk-info");
  const agora = el("span", "rk-agora");
  if (l.erro || !j) {
    pc.textContent = "—";
    info.textContent = l.erro ? "erro ao calcular" : "sem dados";
  } else {
    desenharFaixa(faixa, { acerto: j.acerto, inf: j.ic_inf, sup: j.ic_sup, be: r.break_even });
    faixa.style.setProperty("--cor-faixa", j.vantagem ? css("--marca") : css("--texto-3"));
    pc.append(document.createTextNode(j.decididas ? pct(j.acerto) : "—"), el("small", "", st === 2 ? "(amostra pequena)" : `${j.decididas} op.`));
    info.append(`${j.decididas} operações`);
    if (!S.ativas.has(l.id)) info.append(" · desmarcada");
  }
  info.append(agora);
  S.rkAgora[l.id] = agora;
  const s = l.selo || { codigo: "poucos", texto: "Poucos dados" };
  const selo = el("span", `selo ${s.codigo}`, s.texto + (s.codigo === "comprovada" && s.perdendo_forca ? " · perdendo força" : ""));
  bt.append(el("span", "rk-pos", String(pos)), nome, faixa, pc, info, selo);
  const mais = el("div", "rk-mais");
  mais.appendChild(el("p", "", e.simples || e.descricao));
  const dl = el("dl");
  const linhas = [stats("Recente", j, r.janela), stats("Histórico", l.historico, r.velas)];
  if (l.forca && l.forca.estado) linhas.push(["Força", l.forca.estado]);
  if (j && j.p_holm != null) {
    const nTestes = r.testes || r.linhas.length;
    linhas.push(["Vários testes", j.vantagem_simples && !j.vantagem
      ? `A margem de erro fica acima do mínimo, mas não passa na correção para ${nTestes} estratégias testadas ao mesmo tempo (Holm). Pode ser sorte.`
      : `Correção de Holm para ${nTestes} estratégias testadas ao mesmo tempo: ${j.vantagem ? "passa" : "não se aplica (sem vantagem)"}.`]);
  }
  for (const [dt, dd] of linhas) dl.append(el("dt", "", dt), el("dd", "", dd));
  mais.appendChild(dl);
  bt.addEventListener("click", () => {
    const aberto = li.classList.toggle("aberto");
    bt.setAttribute("aria-expanded", String(aberto));
    if (aberto) S.rkAbertos.add(l.id); else S.rkAbertos.delete(l.id);
  });
  li.append(bt, mais);
  return li;
}
function aplicarRanking(r) {
  S.ranking = r;
  S.lider = r.lider !== undefined ? r.lider : r.melhor;
  setTxt($("rkSub"), `${r.ordem || ""} Recente = últimas ${r.janela} velas; histórico = ${r.velas} velas. Mínimo para lucrar: ${pct(r.break_even, 1)}.`);
  setTxt($("rkCriterio"), r.criterio);
  const caixa = $("rkGrupos"); caixa.replaceChildren();
  S.rkAgora = {};
  const info = r.lider_info || {};
  if (info.desafiante) {
    const faltam = info.confirmacao - info.contagem;
    caixa.appendChild(el("p", "rk-candidata", `Candidata a líder: ${porId(info.desafiante).nome}. Assume se continuar no topo por mais ${faltam} vela${faltam === 1 ? "" : "s"} fechada${faltam === 1 ? "" : "s"} (evita trocar a cada vela).`));
  }
  const grupos = [
    { titulo: "Com vantagem comprovada", st: [0] },
    { titulo: "Sem vantagem comprovada", st: [1] },
    { titulo: `Poucos dados (menos de ${r.min_ops_amostra || 30} operações)`, st: [2, 3], recolhido: true },
  ];
  r.linhas.forEach((l, i) => { l._pos = i + 1; });
  for (const g of grupos) {
    const linhas = r.linhas.filter((l) => g.st.includes(statusLinha(l, r)));
    if (!linhas.length) continue;
    const box = g.recolhido ? el("details", "rk-grupo") : el("section", "rk-grupo");
    const cab = g.recolhido ? el("summary", "", `${g.titulo} · ${linhas.length}`) : el("h3", "", `${g.titulo} · ${linhas.length}`);
    const ol = el("ol", "rk-lista");
    for (const l of linhas) ol.appendChild(linhaRanking(l, l._pos, r, S.lider));
    box.append(cab, ol);
    caixa.appendChild(box);
  }
  atualizarAgoraRanking();
  desenharTabelaRk(r);
  desenharMarcadores();
}
function atualizarAgoraRanking() {
  for (const [id, alvo] of Object.entries(S.rkAgora)) {
    const s = S.estados[id], txt = textoAgora(s);
    alvo.className = `rk-agora ${s ? s.estado : ""} ${s && s.dir ? s.dir : ""}`;
    setTxt(alvo, txt ? ` · ${txt}` : "");
  }
}
function desenharTabelaRk(r) {
  const t = $("rkTabela"); t.replaceChildren();
  const cab = el("tr");
  ["Usar", "Estratégia", "Ops (recente)", "Acerto", "Margem de erro", "Lucro*", "Ops (histórico)", "Acerto hist.", "Força", "Selo"]
    .forEach((h) => cab.appendChild(el("th", "", h)));
  t.appendChild(cab);
  for (const l of r.linhas) {
    const tr = el("tr"), j = l.janela || {}, h = l.historico || {};
    const cb = el("input"); cb.type = "checkbox"; cb.checked = S.ativas.has(l.id); cb.setAttribute("aria-label", `Usar ${l.nome}`);
    cb.addEventListener("change", () => alternarEstrategia(l.id, cb.checked));
    const td0 = el("td"); td0.appendChild(cb); tr.appendChild(td0);
    [l.nome, j.operacoes ?? "—", pct(j.acerto, 1), j.ic_inf == null ? "—" : `${pct(j.ic_inf, 1)} a ${pct(j.ic_sup, 1)}`, num(j.lucro, 1),
     h.operacoes ?? "—", pct(h.acerto, 1), (l.forca || {}).estado || "—", (l.selo || {}).texto || "—"]
      .forEach((v) => tr.appendChild(el("td", "", String(v))));
    t.appendChild(tr);
  }
}
function alternarEstrategia(id, ligado) {
  if (ligado) S.ativas.add(id); else S.ativas.delete(id);
  store.set("ativas", [...S.ativas]);
  enviar({ acao: "ativas", ativas: [...S.ativas] });
  if (S.ranking) aplicarRanking(S.ranking);
}

// ================================================================== estado de cada estratégia (a cada segundo)
function aplicarEstado(msg) {
  S.fechaEm = msg.fecha_em;
  S.offset = msg.agora - Date.now() / 1000;
  if (typeof msg.limite === "number") S.limite = msg.limite;
  if (msg.lider !== undefined) S.lider = msg.lider;
  S.estados = Object.fromEntries(msg.estrategias.map((s) => [s.id, s]));
  atualizarAgoraRanking();
  aplicarVeredito(msg.veredito);
}

// ================================================================== mercado em palavras simples + resumo técnico
const NIVEL = { Fraca: 1, "Média": 2, Forte: 3, Calmo: 1, Normal: 2, Agitado: 3 };
function cartaoMercado(id, { classe = "", icone, valor, nivel, extra }) {
  const c = $(id);
  c.className = "m-cartao " + classe;
  if (icone) trocarIcone(c, icone);
  setTxt(c.querySelector("b"), valor);
  const m = c.querySelector(".medidor"); if (m && nivel !== undefined) m.dataset.n = String(nivel);
  if (extra !== undefined) setTxt(c.querySelector(".m-extra"), extra);
}
function secaoTecnica(titulo, valor, texto, explica) {
  const s = el("section"), h = el("h4", "", titulo);
  const q = el("button", "q", "?"); q.type = "button"; q.dataset.dica = explica; q.setAttribute("aria-label", `Explicar ${titulo}`);
  h.appendChild(q);
  s.append(h, el("p", "valor", valor), el("p", "", texto));
  return s;
}
function aplicarAnalise(a) {
  S.analise = a;
  setTxt($("mCriterio"), a.criterio || "");
  const h = a.humano || { ok: false, frase: `Análise indisponível: ${a.motivo || "sem dados"}.` };
  setTxt($("mFrase"), h.frase); setTxt($("resumoTexto"), h.frase);
  if (!h.ok) return;
  cartaoMercado("mTend", { classe: { SUBINDO: "ALTA", DESCENDO: "BAIXA", LATERAL: "" }[h.tendencia],
                           icone: { SUBINDO: "i-cima", DESCENDO: "i-baixo", LATERAL: "i-lado" }[h.tendencia],
                           valor: h.tendencia, nivel: NIVEL[h.forca], extra: `força ${h.forca}` });
  cartaoMercado("mMov", { icone: "i-onda", valor: h.movimento, nivel: NIVEL[h.movimento],
                          extra: { Calmo: "pouca oscilação", Normal: "oscilação comum", Agitado: "oscilações grandes" }[h.movimento] });
  velaAtual(null);
  const dist = a.distancia_ma_atr, incl = a.inclinacao_atr;
  const tendTxt = `O preço está ${num(Math.abs(dist))} ATR ${dist >= 0 ? "acima" : "abaixo"} da média das últimas 50 velas. `
    + `A média ${incl >= 0 ? "subiu" : "caiu"} ${num(Math.abs(incl))} ATR nas últimas 10 velas.`;
  const vela = a.vela_atual || {};
  $("mTecnico").replaceChildren(
    secaoTecnica("Tendência", { ALTA: "Alta", BAIXA: "Baixa", LATERAL: "Lateral" }[a.tendencia], tendTxt,
      "Alta: preço acima da média de 50 velas e a média subindo mais de 0,5 ATR em 10 velas. Baixa: o inverso. Senão, lateral."),
    secaoTecnica("Força do movimento", `ADX ${num(a.adx, 0)} · ${a.forca}`, "Mede a força, não a direção. Abaixo de 20 é fraca; de 20 a 25, média; acima de 25, forte.",
      "ADX (14 velas): índice de força da tendência, de 0 a 100."),
    secaoTecnica("Tamanho das velas", `Percentil ${num(a.atr_percentil, 0)} · ${a.volatilidade}`,
      `Tamanho médio (ATR): ${num(a.atr, S.casas)}. Perto do percentil 50 é normal; acima de 90, muito agitado; abaixo de 10, muito parado.`,
      "ATR (14 velas): tamanho médio das velas. O percentil compara com as últimas 500 velas."),
    secaoTecnica("Vela atual", { ALTA: "Verde (subindo)", BAIXA: "Vermelha (caindo)", DOJI: "Sem corpo (indecisão)" }[vela.direcao] || "—",
      `Corpo de ${num(vela.corpo_atr)} ATR (${vela.fonte || "—"}).`, "Tamanho do corpo da vela comparado ao tamanho médio (ATR)."),
  );
}
function velaAtual(v) {
  if (!S.analise || !S.analise.ok) return;
  let dir;
  if (v) { const c = v[4] - v[1]; dir = c > 0 ? "ALTA" : c < 0 ? "BAIXA" : "DOJI"; }
  else dir = S.analise.vela_atual.direcao;
  cartaoMercado("mVela", { classe: dir === "DOJI" ? "" : dir, icone: dir === "ALTA" ? "i-cima" : dir === "BAIXA" ? "i-baixo" : "i-lado",
                           valor: { ALTA: "Subindo", BAIXA: "Descendo", DOJI: "Parada" }[dir], extra: v ? "em formação" : "" });
}

// ================================================================== top 3
let assinaturaTop = "";
function sparkline(valores, variacao) {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("class", "spark"); s.setAttribute("viewBox", "0 0 100 30"); s.setAttribute("preserveAspectRatio", "none"); s.setAttribute("aria-hidden", "true");
  if (!valores || valores.length < 2) return s;
  const min = Math.min(...valores), max = Math.max(...valores), amp = max - min || 1;
  const pts = valores.map((v, i) => [(100 * i) / (valores.length - 1), 27 - (24 * (v - min)) / amp]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("");
  const cor = variacao > 0.0001 ? css("--alta") : variacao < -0.0001 ? css("--baixa") : css("--marca");
  const id = "g" + Math.random().toString(36).slice(2, 8);
  const defs = document.createElementNS(NS, "defs"), grad = document.createElementNS(NS, "linearGradient");
  grad.setAttribute("id", id); grad.setAttribute("x1", "0"); grad.setAttribute("y1", "0"); grad.setAttribute("x2", "0"); grad.setAttribute("y2", "1");
  for (const [off, op] of [["0", ".32"], ["1", "0"]]) {
    const st = document.createElementNS(NS, "stop"); st.setAttribute("offset", off); st.setAttribute("stop-color", cor); st.setAttribute("stop-opacity", op); grad.appendChild(st);
  }
  defs.appendChild(grad);
  const area = document.createElementNS(NS, "path"); area.setAttribute("d", `${d}L100,30L0,30Z`); area.setAttribute("fill", `url(#${id})`);
  const linha = document.createElementNS(NS, "path"); linha.setAttribute("d", d); linha.setAttribute("fill", "none");
  linha.setAttribute("stroke", cor); linha.setAttribute("stroke-width", "1.6"); linha.setAttribute("vector-effect", "non-scaling-stroke"); linha.setAttribute("stroke-linejoin", "round");
  s.append(defs, area, linha);
  return s;
}
function anelPontos(p) {
  const c = 2 * Math.PI * 22, caixa = el("div", "anel-pts");
  const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", "0 0 52 52"); s.setAttribute("aria-hidden", "true");
  for (const [cls, extra] of [["t", {}], ["p", { "stroke-dasharray": c, "stroke-dashoffset": c * (1 - p / 100) }]]) {
    const ci = document.createElementNS(NS, "circle");
    ci.setAttribute("class", cls); ci.setAttribute("cx", "26"); ci.setAttribute("cy", "26"); ci.setAttribute("r", "22");
    for (const [k, v] of Object.entries(extra)) ci.setAttribute(k, String(v));
    s.appendChild(ci);
  }
  caixa.append(s, el("b", "", String(Math.round(p))));
  return caixa;
}
function itemTop(r, i) {
  const li = el("li", "top-item"); li.dataset.simbolo = r.simbolo; li.tabIndex = 0; li.setAttribute("role", "button");
  li.setAttribute("aria-label", `${i + 1}º ${nomeAtivo(r.simbolo)}, nota ${Math.round(r.pontos)} de 100. ${r.porque || ""}. Abrir no gráfico.`);
  const nome = el("div", "top-nome"); nome.appendChild(el("b", "", nomeAtivo(r.simbolo)));
  const tag = el("span", "tag", "No gráfico"); tag.hidden = true; nome.appendChild(tag);
  const t = r.tendencia || "LATERAL";
  const tend = el("span", `tend ${t}`);
  tend.append(svgUso(t === "ALTA" ? "i-cima" : t === "BAIXA" ? "i-baixo" : "i-lado"), document.createTextNode({ ALTA: "Subindo", BAIXA: "Descendo", LATERAL: "Lateral" }[t]));
  const spark = el("span", "spark-caixa");
  const vv = r.variacao;
  spark.append(sparkline(r.spark, vv || 0));
  if (vv !== null && vv !== undefined) spark.appendChild(el("span", `spark-var ${vv > 0.0001 ? "ALTA" : vv < -0.0001 ? "BAIXA" : "LATERAL"}`, `${comSinal(100 * vv, 2)}%`));
  const linha2 = el("div", "top-linha2"); linha2.append(tend, spark);
  const nota = el("ul", "top-nota");
  nota.setAttribute("aria-label", "Por que essa nota");
  for (const c of r.explicacao || []) {
    const item = el("li"); const br = el("span", "br"); const fill = el("i"); fill.style.width = `${(100 * c.pontos) / c.max}%`; br.appendChild(fill);
    item.append(el("span", "nm", c.nome), br, el("span", "pt", `${num(c.pontos, 0)}/${c.max}`), el("span", "tx", c.texto));
    item.title = `${c.nome}: ${c.texto}`;
    nota.appendChild(item);
  }
  li.append(el("span", "top-pos", String(i + 1)), nome, anelPontos(r.pontos), linha2, el("div", "top-porque", r.porque || r.resumo || ""), nota);
  const abrir = () => abrirAtivo(r.simbolo);
  li.addEventListener("click", abrir);
  li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); } });
  return li;
}
function aplicarTop(msg) {
  setTxt($("topInfo"), `${msg.timeframe} · ${fmtHora(msg.atualizado)}${msg.carregando ? ` · carregando ${msg.carregando}` : ""}`);
  $("qTop").dataset.dica = "Nota de 0 a 100:\n• " + msg.regra.join("\n• ");
  const chave = JSON.stringify(msg.itens.map((r) => [r.simbolo, r.pontos, r.porque, r.tendencia, r.spark && r.spark.slice(-1)[0], r.variacao])) + msg.carregando;
  if (chave !== assinaturaTop) {
    assinaturaTop = chave;
    const lista = $("topLista"); lista.replaceChildren();
    if (!msg.itens.length) lista.appendChild(el("li", "vazio-txt", msg.carregando ? "Carregando históricos dos ativos…" : "Nenhum ativo aberto e com dados no momento."));
    msg.itens.forEach((r, i) => lista.appendChild(itemTop(r, i)));
  }
  marcarTopAtual();
  const tab = $("topTodos"); tab.replaceChildren();
  const cab = el("tr"); ["Ativo", "Nota", "Movimento", "Tendência", "Estratégia", "Situação"].forEach((h) => cab.appendChild(el("th", "", h))); tab.appendChild(cab);
  for (const r of msg.todos) {
    const tr = el("tr"), c = r.componentes || {};
    [nomeAtivo(r.simbolo), num(r.pontos, 1), c.volatilidade !== undefined ? num(c.volatilidade, 1) : "—", c.tendencia !== undefined ? num(c.tendencia, 1) : "—",
     c.estrategia !== undefined ? num(c.estrategia, 0) : "—", r.elegivel ? r.porque : (r.motivo || "—")]
      .forEach((v) => tr.appendChild(el("td", "", String(v))));
    tab.appendChild(tr);
  }
}
function marcarTopAtual() {
  for (const li of $("topLista").querySelectorAll(".top-item")) {
    const atual = li.dataset.simbolo === S.simbolo;
    li.classList.toggle("atual", atual);
    li.querySelector(".tag").hidden = !atual;
  }
}
function abrirAtivo(simbolo) {
  if (DEMO) { toast("Demonstração", "Na demonstração o gráfico não troca de ativo. Ao vivo, isto abre o ativo sem recarregar a página.", "", "i-olho"); return; }
  const a = S.ativos.find((x) => x.symbol === simbolo);
  if (a) { $("selMercado").value = a.market_display_name; preencherAtivos(); }
  else if (![...$("selAtivo").options].some((o) => o.value === simbolo)) $("selAtivo").add(new Option(simbolo, simbolo));
  $("selAtivo").value = simbolo;
  conectar();
}

// ================================================================== operações da sessão (filtradas por ativo + tempo)
/* Cada operação guarda o contexto (ativo + tempo gráfico + sid). "Este ativo" mostra só as do contexto
   atual (padrão); "Todas" mostra todas, cada uma com o rótulo do ativo e do tempo. Totais separados. */
const ROTULO_RES = { WIN: "WIN", LOSS: "LOSS", EMPATE: "EMPATE", CANCELADO: "cancelada" };
const MAX_OPS = 300;
const contextoAtual = (o) => o.simbolo === S.simbolo && o.tf === S.tf;
function adicionarSinal(msg) {
  S.ops.push({ sid: S.sid, op: msg.op, simbolo: msg.ativo, tf: msg.timeframe || S.tf, id: msg.id, nome: msg.nome,
               dir: msg.dir, t: msg.t, principal: !!msg.principal, resultado: null });
  if (S.ops.length > MAX_OPS) S.ops.splice(0, S.ops.length - MAX_OPS);
  desenharOps();
}
function aplicarResultado(msg) {
  const o = S.ops.find((x) => x.sid === S.sid && x.op === msg.op);
  if (o) { o.resultado = msg.resultado; if (msg.principal !== undefined) o.principal = !!msg.principal; }
  desenharOps();
}
function cancelarPendentes() {   // trocou de ativo/tempo: o servidor registra as abertas como CANCELADO
  for (const o of S.ops) if (!o.resultado) o.resultado = "CANCELADO";
}
function totais(lista) {
  const t = { WIN: 0, LOSS: 0, EMPATE: 0 }, f = { WIN: 0, LOSS: 0, EMPATE: 0 };
  for (const o of lista) if (o.resultado in t) { t[o.resultado]++; if (o.principal) f[o.resultado]++; }
  return `Avisadas pelo Farol: ${f.WIN} WIN · ${f.LOSS} LOSS · ${f.EMPATE} EMPATE  |  Todas as estratégias: ${t.WIN} WIN · ${t.LOSS} LOSS · ${t.EMPATE} EMPATE`;
}
function desenharOps() {
  const todas = S.opsAba === "todas";
  for (const [id, aba] of [["opsAbaAtivo", "ativo"], ["opsAbaTodas", "todas"]]) {
    const b = $(id); b.setAttribute("aria-selected", String(S.opsAba === aba)); b.classList.toggle("on", S.opsAba === aba);
  }
  setTxt($("opsAbaAtivo"), S.simbolo ? `Este ativo (${nomeAtivo(S.simbolo)} ${S.tf})` : "Este ativo");
  const lista = todas ? S.ops : S.ops.filter(contextoAtual);
  setTxt($("placar"), lista.length ? totais(lista) : "");
  const ul = $("listaOps"); ul.replaceChildren();
  if (!lista.length) {
    ul.appendChild(el("li", "vazio-txt", todas ? "Nenhuma operação nesta sessão ainda."
      : "Nenhuma operação neste ativo e tempo gráfico ainda. Cada sinal das estratégias marcadas aparece aqui com o resultado."));
    return;
  }
  for (const o of lista.slice(-60).reverse()) {
    const li = el("li", `op ${o.resultado || "pend"}${o.principal ? " principal" : ""}`);
    li.dataset.simbolo = o.simbolo; li.dataset.tf = o.tf;
    const res = el("span", `op-res ${o.resultado || "pend"}`);
    if (o.resultado === "WIN") res.append(svgUso("i-check"), document.createTextNode("WIN"));
    else if (o.resultado === "LOSS") res.append(svgUso("i-x"), document.createTextNode("LOSS"));
    else res.textContent = o.resultado ? ROTULO_RES[o.resultado] : "aguardando";
    const dir = el("span", `op-dir ${o.dir}`, `${SETA[o.dir]} ${ACAO[o.dir]}`);
    li.append(el("span", "op-hora numero", fmtHora(o.t + S.seg)), el("span", "op-ctx", `${nomeAtivo(o.simbolo)} · ${o.tf}`),
              el("span", "op-nome", o.nome + (o.principal ? " ★" : "")), dir, res);
    li.setAttribute("aria-label", `${fmtHora(o.t)} ${nomeAtivo(o.simbolo)} ${o.tf}, ${o.nome}, ${ACAO[o.dir]}, ${o.resultado ? ROTULO_RES[o.resultado] : "aguardando resultado"}${o.principal ? ", entrada avisada" : ""}`);
    ul.appendChild(li);
  }
}

// ================================================================== conexão com o servidor local
const TEXTO_CONEXAO = { conectado: "Deriv conectada", conectando: "Conectando…", reconectando: "Reconectando…", desconectado: "Sem conexão" };
function setConexao(msg) {
  $("pontoDeriv").className = "ponto " + msg.estado;
  setTxt($("txtDeriv"), TEXTO_CONEXAO[msg.estado] || msg.texto);
  $("conexao").title = `${msg.texto}${msg.quedas ? ` · reconexões: ${msg.quedas}` : ""}`;
}
function setStatus(texto, nivel = "info") {
  $("conexao").dataset.status = texto;
  if (nivel === "erro") toast("Atenção", texto, "erro", "i-alerta", 12000);
  else if (nivel === "aviso") toast("Aviso", texto, "prep", "i-alerta", 10000);
}
function enviar(obj) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(obj)); }
function enviarPreferencias() { enviar({ observacao: P.obs, avisar_obs: P.avisarObs, limite_formacao: S.limite }); }
function abrirWs() {
  return new Promise((ok, falha) => {
    if (S.ws && S.ws.readyState === 1) { ok(); return; }
    const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    S.ws = sock;
    sock.onopen = () => ok();
    sock.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); }
      catch { setStatus("Mensagem inválida do servidor (ignorada).", "erro"); return; }
      tratar(msg);
    };
    sock.onclose = () => {
      if (S.ws === sock) S.ws = null;
      falha(new Error("conexão fechada"));
      if (S.conectado) {
        $("pontoDeriv").className = "ponto erro"; setTxt($("txtDeriv"), "Servidor local fora");
        setTimeout(() => { if (S.conectado) conectar(); }, 3000);
      }
    };
  });
}
/* Toda mensagem do servidor traz o sid do contexto (ativo + tempo) em que foi gerada. Depois de uma troca,
   respostas atrasadas do contexto anterior são descartadas aqui (condição de corrida). */
function tratar(msg) {
  if (!DEMO && msg.tipo !== "conexao" && msg.sid !== S.sid) {
    S.descartadas++; document.documentElement.dataset.descartadas = String(S.descartadas);
    return;
  }
  switch (msg.tipo) {
    case "carga": aplicarCarga(msg); break;
    case "status": setStatus(msg.texto, msg.nivel); break;
    case "conexao": setConexao(msg); break;
    case "historico": aplicarHistorico(msg); break;
    case "vela":
      atualizarBarra(msg.v);
      setTxt($("lgPreco"), msg.v[4].toFixed(S.casas));
      if (S.fechaEm && msg.v[0] + S.seg >= S.fechaEm - 1) velaAtual(msg.v);
      break;
    case "estado": aplicarEstado(msg); break;
    case "ranking": aplicarRanking(msg); break;
    case "analise": aplicarAnalise(msg); break;
    case "decisao": aplicarVeredito(msg.veredito); break;
    case "aviso": mostrarAviso(msg); break;
    case "top3": aplicarTop(msg); break;
    case "sinal":
      S.sinais.push({ t: msg.t, id: msg.id, dir: msg.dir, principal: msg.principal });
      desenharMarcadores();
      if (msg.registrado) adicionarSinal(msg);
      break;
    case "resultado": aplicarResultado(msg); break;
    default: break;
  }
}
function aplicarHistorico(msg) {
  S.seg = msg.seg; S.casas = msg.casas; S.simbolo = msg.simbolo; S.tf = msg.timeframe;
  S.janelaEntrada = msg.janela_entrada || Math.min(60, Math.max(10, msg.seg * 0.25));
  S.barras = msg.velas.map(barra); S.sinais = msg.sinais; G.assinatura = "";
  if (G.serie) {
    G.serie.applyOptions({ priceFormat: { type: "price", precision: S.casas, minMove: Math.pow(10, -S.casas) } });
    G.serie.setData(S.barras);
    mostrarUltimasVelas();
  }
  desenharMarcadores();
  $("vazio").hidden = !!G.chart;
  setTxt($("lgAtivo"), `${nomeAtivo(msg.simbolo)} · ${msg.timeframe}`);
  setTxt($("mAtivo"), `${nomeAtivo(msg.simbolo)} ${msg.timeframe}`);
  setTxt($("chipAtivo"), `${nomeAtivo(msg.simbolo)} · ${msg.timeframe}`);
  const ult = msg.velas[msg.velas.length - 1];
  if (ult) setTxt($("lgPreco"), ult[4].toFixed(S.casas));
  document.body.dataset.contexto = `${msg.simbolo}|${msg.timeframe}`;
  marcarTopAtual();
  desenharOps();
}
/* Troca de ativo/tempo: descarta TODO o estado do contexto anterior antes de pedir o novo. */
function limparContexto(simbolo, tf) {
  cancelarPendentes();
  S.simbolo = simbolo; S.tf = tf;
  S.barras = []; S.sinais = []; S.estados = {}; S.ranking = null; S.lider = null; S.analise = null;
  S.veredito = null; S.fechaEm = null; S.carga = null; S.rkAgora = {};
  G.assinatura = ""; G.grupos = new Map();
  if (G.serie) { G.serie.setData([]); G.serie.setMarkers([]); }
  $("vazio").hidden = false; setTxt($("vazio"), `Carregando velas de ${nomeAtivo(simbolo)} ${tf}…`);
  $("dicaGrafico").hidden = true;
  setTxt($("lgAtivo"), `${nomeAtivo(simbolo)} · ${tf}`); setTxt($("lgPreco"), "");
  setTxt($("mAtivo"), `${nomeAtivo(simbolo)} ${tf}`); setTxt($("mFrase"), "—");
  setTxt($("resumoTexto"), "Calculando o resumo do mercado…");
  $("rkGrupos").replaceChildren(el("p", "vazio-txt", "Calculando as estratégias…"));
  $("rkTabela").replaceChildren();
  assinaturaTop = ""; $("topLista").replaceChildren(el("li", "vazio-txt", `Carregando ativos no ${tf}…`)); setTxt($("topInfo"), "");
  document.body.dataset.contexto = "";
  assinaturaVeredito = "";
  desenharOps();
}

// ================================================================== conectar / parar
function timeframeEscolhido() { return $("selTf").value === "custom" ? $("inpTfCustom").value.trim().toUpperCase() : $("selTf").value; }
function botaoConectar(ligado) {
  const b = $("btnConectar");
  b.classList.toggle("parar", ligado);
  b.querySelector("use").setAttribute("href", ligado ? "#i-stop" : "#i-play");
  setTxt(b.querySelector("span"), ligado ? "Parar" : "Conectar");
  b.setAttribute("aria-label", ligado ? "Parar" : "Conectar");
}
async function conectar() {
  const simbolo = $("selAtivo").value, tf = timeframeEscolhido();
  if (!simbolo || !tf) { $("dlgAtivo").showModal(); return; }
  const exp = Math.min(60, Math.max(1, parseInt($("inpExp").value, 10) || 1));
  const payout = Math.min(500, Math.max(1, parseFloat($("inpPayout").value) || 85));
  store.set("escolha", { mercado: $("selMercado").value, simbolo, tf: $("selTf").value, custom: $("inpTfCustom").value, exp, payout });
  S.conectado = true; botaoConectar(true);
  S.sid = `s${Date.now().toString(36)}${++S.nSid}`;   // novo contexto: o que chegar com outro sid é descartado
  const sid = S.sid;
  limparContexto(simbolo, tf.toUpperCase());
  setTxt($("chipAtivo"), `${nomeAtivo(simbolo)} · ${tf}`);
  mostrarVeredito(vereditoLocal("CARREGANDO"));
  pararTimerCarga();
  S.timerCarga = setTimeout(() => {
    if (S.sid === sid && (!S.veredito || S.veredito.estado === "CARREGANDO"))
      mostrarVeredito(vereditoLocal("ERRO", `O carregamento de ${nomeAtivo(simbolo)} ${tf} passou de 30 s. Verifique a internet e toque em “Tentar de novo”.`));
  }, TEMPO_CARGA);
  try { await abrirWs(); } catch { mostrarVeredito(vereditoLocal("ERRO", "Sem conexão com o servidor local do Farol (python live.py está aberto?).")); return; }
  if (S.sid !== sid) return;   // outra troca aconteceu enquanto a conexão abria
  enviar({ acao: "assinar", sid, simbolo, timeframe: tf, expiracao: exp, payout, ativas: [...S.ativas],
           observacao: P.obs, avisar_obs: P.avisarObs, limite_formacao: S.limite });
}
function parar() {
  S.conectado = false; botaoConectar(false);
  enviar({ acao: "parar" });
  pararTimerCarga(); cancelarPendentes(); desenharOps();
  S.sid = null; S.fechaEm = null; S.veredito = null;
  mostrarVeredito(vereditoLocal("INICIO"));
}
function atualizarBeInfo() {
  const p = Math.min(500, Math.max(1, parseFloat($("inpPayout").value) || 85)) / 100;
  setTxt($("beInfo"), `Com payout de ${num(p * 100, 0)}%, é preciso acertar mais de ${pct(1 / (1 + p), 1)} das operações só para empatar.`);
}

// ================================================================== modos, letra, observação e alertas
function aplicarModo() {
  const simples = P.modo !== "detalhado";
  document.body.classList.toggle("modo-simples", simples);
  $("btnSimples").classList.toggle("on", simples); $("btnSimples").setAttribute("aria-pressed", String(simples));
  $("btnDetalhado").classList.toggle("on", !simples); $("btnDetalhado").setAttribute("aria-pressed", String(!simples));
}
function aplicarLetra() {
  if (!["p", "m", "g"].includes(P.letra)) P.letra = "m";
  document.documentElement.dataset.letra = P.letra;
  for (const b of document.querySelectorAll(".grupo-letra button")) b.setAttribute("aria-pressed", String(b.dataset.letra === P.letra));
  if (G.chart) G.chart.applyOptions({ layout: { fontSize: TAMANHO_FONTE_GRAFICO[P.letra] } });
}
function aplicarObs() {
  $("btnObs").setAttribute("aria-pressed", String(P.obs));
  $("btnObs").title = P.obs ? "Modo observação LIGADO: quando nada está comprovado, mostra a melhor candidata (não é recomendação)"
                            : "Modo observação: mostra a melhor candidata quando nenhuma estratégia está comprovada (não é recomendação)";
}
function aplicarTodos() {
  $("chkTodos").checked = P.todos;
  document.body.classList.toggle("todos-sinais", P.todos);
}
function atualizarBotaoNotif() {
  const b = $("btnNotif");
  if (!("Notification" in window)) { b.textContent = "Sem notificações"; b.disabled = true; return; }
  b.textContent = Notification.permission === "granted" ? "Notificações permitidas" : Notification.permission === "denied" ? "Notificações bloqueadas" : "Permitir notificações";
  b.disabled = Notification.permission !== "default";
}
async function testarAlertas() {
  const b = $("btnTestar"); b.disabled = true;
  try { audio(); } catch { /* sem áudio */ }
  if ("Notification" in window && Notification.permission === "default") {
    try { await Notification.requestPermission(); } catch { /* o navegador recusou o pedido */ }
    atualizarBotaoNotif();
  }
  if (A.ctx && A.ctx.state !== "running") toast("Áudio bloqueado", "O navegador bloqueou o som. Clique na página e tente de novo.", "erro", "i-alerta");
  if (!P.som) toast("Som desligado", "O teste toca mesmo assim, mas nos avisos reais você não ouviria nada.", "prep", "i-alerta", 10000);
  try {
    const lista = await (await fetch("/api/avisos/teste")).json();
    for (const a of lista) { mostrarAviso(a, true); await espera(1800); }
  } catch (e) { toast("Teste indisponível", "Não foi possível falar com o servidor local.", "erro", "i-alerta"); }
  if (!("Notification" in window)) toast("Notificações", "Este navegador não tem notificações.", "erro", "i-alerta", 10000);
  else if (Notification.permission !== "granted") toast("Notificações bloqueadas", "Clique no cadeado ao lado do endereço e permita notificações.", "erro", "i-alerta", 12000);
  b.disabled = false;
}
function ligarControles() {
  $("btnConectar").onclick = () => { if (S.conectado) parar(); else if (!DEMO) conectar(); };
  $("vAcao").onclick = () => { if (S.veredito && S.veredito.estado === "ERRO" || $("veredito").dataset.estado === "ERRO") conectar(); else $("dlgAtivo").showModal(); };
  $("opsAbaAtivo").onclick = () => { S.opsAba = "ativo"; store.set("opsAba", "ativo"); desenharOps(); };
  $("opsAbaTodas").onclick = () => { S.opsAba = "todas"; store.set("opsAba", "todas"); desenharOps(); };
  $("btnAtivo").onclick = () => $("dlgAtivo").showModal();
  $("dlgAtivo").addEventListener("close", () => { if ($("dlgAtivo").returnValue === "conectar" && !DEMO) conectar(); });
  $("inpPayout").addEventListener("input", atualizarBeInfo);
  $("btnSimples").onclick = () => { P.modo = "simples"; store.set("modo", P.modo); aplicarModo(); };
  $("btnDetalhado").onclick = () => { P.modo = "detalhado"; store.set("modo", P.modo); aplicarModo(); };
  for (const b of document.querySelectorAll(".grupo-letra button")) b.onclick = () => { P.letra = b.dataset.letra; store.set("letra", P.letra); aplicarLetra(); };
  $("btnObs").onclick = () => {
    P.obs = !P.obs; store.set("observacao", P.obs); aplicarObs();
    if (DEMO) { if (DEMO === "aguardar" || DEMO === "observacao") irDemo(P.obs ? "observacao" : "aguardar"); return; }
    enviarPreferencias();
    toast(P.obs ? "Modo observação ligado" : "Modo observação desligado",
          P.obs ? "Quando nenhuma estratégia estiver comprovada, você verá a melhor candidata, marcada como NÃO COMPROVADA. Sem som de entrada."
                : "O veredito volta a mostrar só o que tem vantagem comprovada.", "discreto", "i-olho");
  };
  $("chkTodos").onchange = () => { P.todos = $("chkTodos").checked; store.set("todosSinais.v2", P.todos); aplicarTodos(); G.assinatura = ""; desenharMarcadores(); };
  $("btnAlertas").onclick = () => { atualizarBotaoNotif(); $("dlgAlertas").showModal(); };
  $("chkSom").checked = P.som;
  $("chkSom").onchange = () => { P.som = $("chkSom").checked; store.set("som", P.som); if (P.som) tocar("formando"); };
  $("inpVolume").value = P.volume; setTxt($("volTxt"), `${P.volume}%`);
  $("inpVolume").oninput = () => { P.volume = Number($("inpVolume").value); store.set("volume", P.volume); setTxt($("volTxt"), `${P.volume}%`); };
  $("inpVolume").onchange = () => tocar("formando", true);
  $("inpLimite").oninput = () => { S.limite = Number($("inpLimite").value); setTxt($("limiteTxt"), `${S.limite}%`); };
  $("inpLimite").onchange = () => { P.limite = S.limite; store.set("limite", P.limite); enviarPreferencias(); if (S.veredito) { assinaturaVeredito = ""; mostrarVeredito(S.veredito); } };
  $("chkAvisarObs").checked = P.avisarObs;
  $("chkAvisarObs").onchange = () => { P.avisarObs = $("chkAvisarObs").checked; store.set("avisarObs", P.avisarObs); enviarPreferencias(); };
  $("btnNotif").onclick = async () => { if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission(); atualizarBotaoNotif(); };
  $("btnTestar").onclick = testarAlertas;
  const subir = () => scrollTo({ top: 0, behavior: movimentoReduzido() ? "auto" : "smooth" });
  $("vbSubir").onclick = subir;
  $("vBarra").addEventListener("click", (e) => { if (!e.target.closest("button")) subir(); });
}
const movimentoReduzido = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// ================================================================== tour de primeira visita
const PASSOS = [
  { alvo: "veredito", titulo: "Bem-vindo ao Farol", texto: "O Farol só acende quando os dados sustentam. Este cartão diz, em português simples, o que fazer agora: ENTRAR, SE PREPARANDO, AGUARDAR ou CONFLITO. ENTRAR só aparece quando a estratégia líder tem vantagem comprovada, sempre com a probabilidade estimada e a margem de erro. Ao rolar a página, ele vira uma barra fixa no topo." },
  { alvo: "grafico", titulo: "O gráfico", texto: "Velas ao vivo. A linha tracejada marca o fim da vela atual, com a contagem. As setas mostram só a entrada avisada (★) e os sinais da estratégia líder. Ligando “Mostrar todos os sinais”, vários sinais na mesma vela viram uma seta com “×N”; passe o mouse para ver a lista." },
  { alvo: "top", titulo: "Top 3 ativos", texto: "Os ativos com o melhor cenário agora, com nota de 0 a 100 e o motivo de cada parte da nota. Toque em um para trocar o gráfico." },
  { alvo: "alertas", titulo: "Avisos só da líder", texto: "Só a estratégia líder avisa: quando está se formando, quando é hora de entrar e o resultado. Sem vantagem comprovada, silêncio. Aqui você testa os sons e escolhe a partir de quanto % de formação quer ser avisado." },
  { alvo: "modos", titulo: "Simples, Detalhado e tamanho da letra", texto: "No Detalhado você vê o ranking das estratégias, o mercado em palavras simples e as suas operações. Use P, M e G para o tamanho da letra. O botão ? reabre este guia." },
];
const T = { passo: 0 };
function abrirTour() { T.passo = 0; $("tour").hidden = false; mostrarPasso(); }
function fecharTour() {
  $("tour").hidden = true; store.set("tourVisto", true);
  scrollTo({ top: 0, behavior: movimentoReduzido() ? "auto" : "smooth" });   // volta ao veredito
}
function mostrarPasso() {
  const p = PASSOS[T.passo], alvo = document.querySelector(`[data-tour="${p.alvo}"]`);
  setTxt($("tourPasso"), `PASSO ${T.passo + 1} DE ${PASSOS.length} · COMO LER ESTA TELA`);
  setTxt($("tourTitulo"), p.titulo); setTxt($("tourTexto"), p.texto);
  $("tourVoltar").hidden = T.passo === 0;
  setTxt($("tourProximo"), T.passo === PASSOS.length - 1 ? "Entendi" : "Próximo");
  const r = alvo.getBoundingClientRect();
  const visivel = r.top >= alturaTopo() && r.bottom <= innerHeight - 50;
  if (!visivel) alvo.scrollIntoView({ block: "center", behavior: movimentoReduzido() ? "auto" : "smooth" });
  setTimeout(() => posicionarTour(alvo), visivel ? 30 : 380);
}
function posicionarTour(alvo) {
  if ($("tour").hidden) return;
  const r = alvo.getBoundingClientRect(), f = $("tourFoco"), c = $("tourCartao"), m = 8;
  Object.assign(f.style, { left: `${r.left - m}px`, top: `${r.top - m}px`, width: `${r.width + 2 * m}px`, height: `${r.height + 2 * m}px` });
  const cr = c.getBoundingClientRect();
  let y = r.bottom + 16;
  if (y + cr.height > innerHeight - 12) y = r.top - cr.height - 16;
  if (y < 12) y = Math.min(innerHeight - cr.height - 12, Math.max(12, r.top + 12));
  const x = Math.max(16, Math.min(innerWidth - cr.width - 16, r.left));
  Object.assign(c.style, { left: `${x}px`, top: `${y}px` });
}
function ligarTour() {
  $("btnTour").onclick = abrirTour;
  $("tourPular").onclick = fecharTour;
  $("tourVoltar").onclick = () => { T.passo = Math.max(0, T.passo - 1); mostrarPasso(); };
  $("tourProximo").onclick = () => { if (T.passo >= PASSOS.length - 1) fecharTour(); else { T.passo++; mostrarPasso(); } };
  addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("tour").hidden) fecharTour(); });
}

// ================================================================== demonstração (?demo=entrar)
const CENARIOS = { entrar: "Entrar", preparando: "Se preparando", aguardar: "Aguardar", conflito: "Conflito", observacao: "Observação" };
function irDemo(c) { const u = new URL(location.href); u.searchParams.set("demo", c); location.href = u.toString(); }
async function iniciarDemo() {
  $("faixaDemo").hidden = false;
  const nav = $("demoCenarios");
  for (const [c, nome] of Object.entries(CENARIOS)) {
    const u = new URL(location.href); u.searchParams.set("demo", c);
    const a = el("a", c === DEMO ? "on" : "", nome); a.href = u.toString();
    if (c === DEMO) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  }
  P.obs = DEMO === "observacao"; aplicarObs();
  S.conectado = true; botaoConectar(true);
  try {
    const msgs = await (await fetch(`/api/demo/${encodeURIComponent(DEMO)}`)).json();
    if (!Array.isArray(msgs)) throw new Error(msgs.erro || "cenário inválido");
    msgs.forEach(tratar);
  } catch (e) { toast("Demonstração indisponível", String(e.message || e), "erro", "i-alerta"); }
}

// ================================================================== seletores e início
function preencherAtivos() {
  const lista = S.ativos.filter((a) => a.market_display_name === $("selMercado").value);
  const sel = $("selAtivo"); sel.replaceChildren();
  let grupo = null, og = null;
  for (const a of lista) {
    if (a.submarket_display_name !== grupo) { grupo = a.submarket_display_name; og = document.createElement("optgroup"); og.label = grupo; sel.appendChild(og); }
    og.appendChild(new Option(`${a.display_name}${a.exchange_is_open ? "" : "  (fechado)"}`, a.symbol));
  }
}
function medirTopo() {
  const atualizar = () => document.documentElement.style.setProperty("--altura-topo", `${alturaTopo()}px`);
  atualizar();
  if ("ResizeObserver" in window) new ResizeObserver(atualizar).observe($("topo"));
}
async function carregarAtivos(escolha) {
  try {
    const r = await fetch("/api/ativos");
    const dados = await r.json();
    if (!r.ok) throw new Error(dados.erro || r.status);
    S.ativos = dados;
    S.nomes = Object.fromEntries(S.ativos.map((a) => [a.symbol, a.display_name]));
  } catch (e) {
    setStatus("Não foi possível listar os ativos da Deriv: " + e.message, "erro");
    $("selMercado").replaceChildren(new Option("—", ""));
    const sim = escolha.simbolo || "frxEURUSD";
    $("selAtivo").replaceChildren(new Option(sim, sim));
    return;
  }
  const mercados = [...new Set(S.ativos.map((a) => a.market_display_name))];
  const selM = $("selMercado"); selM.replaceChildren();
  mercados.forEach((m) => selM.add(new Option(m, m)));
  const doSimbolo = S.ativos.find((a) => a.symbol === escolha.simbolo);
  selM.value = doSimbolo ? doSimbolo.market_display_name : (escolha.mercado && mercados.includes(escolha.mercado) ? escolha.mercado : mercados[0]);
  preencherAtivos();
  if (doSimbolo) $("selAtivo").value = escolha.simbolo;
  selM.onchange = preencherAtivos;
  setTxt($("chipAtivo"), `${nomeAtivo($("selAtivo").value)} · ${timeframeEscolhido()}`);
}
async function init() {
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";   // abre sempre no topo
  scrollTo(0, 0);
  medirTopo();
  aplicarLetra(); aplicarModo(); aplicarObs(); aplicarTodos();
  criarGrafico();
  ligarDicas(); ligarControles(); ligarTour();
  addEventListener("scroll", () => requestAnimationFrame(atualizarBarraCompacta), { passive: true });
  addEventListener("resize", () => {
    if (!$("tour").hidden) posicionarTour(document.querySelector(`[data-tour="${PASSOS[T.passo].alvo}"]`));
    posicionarLinhaEntrada(); atualizarBarraCompacta();
  });
  setInterval(atualizarRelogio, 250);
  // o navegador só libera o som depois de um gesto do usuário: prepara o áudio no primeiro clique/tecla
  const liberarAudio = () => { try { audio(); } catch { /* sem áudio: os avisos continuam visuais */ } };
  addEventListener("pointerdown", liberarAudio, { once: true });
  addEventListener("keydown", liberarAudio, { once: true });
  S.config = await (await fetch("/api/config")).json();
  const cfg = S.config;
  const salvas = store.get("ativas", null);
  S.ativas = new Set(salvas ? salvas.filter((id) => cfg.estrategias.some((e) => e.id === id)) : cfg.estrategias.map((e) => e.id));
  const [lmin, lmax] = cfg.limite_formacao_faixa || [50, 100];
  S.limite = Math.min(lmax, Math.max(lmin, P.limite || cfg.limite_formacao || 70));
  $("inpLimite").min = lmin; $("inpLimite").max = lmax; $("inpLimite").value = S.limite; setTxt($("limiteTxt"), `${S.limite}%`);
  $("qProgresso").dataset.dica = cfg.explicacao_progresso; $("qLimite").dataset.dica = cfg.explicacao_progresso;
  $("qTop").dataset.dica = "Nota de 0 a 100:\n• " + cfg.regra_scanner.join("\n• ");
  const tfs = $("selTf");
  for (const tf of cfg.timeframes) tfs.add(new Option(tf, tf));
  tfs.add(new Option("Personalizado…", "custom"));
  tfs.onchange = () => { $("campoTfCustom").hidden = tfs.value !== "custom"; };
  const escolha = store.get("escolha", { mercado: null, simbolo: "frxEURUSD", tf: "M5", custom: "", exp: 1, payout: 85 });
  tfs.value = escolha.tf || "M5"; $("inpTfCustom").value = escolha.custom || ""; $("inpExp").value = escolha.exp || 1;
  $("inpPayout").value = escolha.payout || Math.round(cfg.payout * 100);
  $("campoTfCustom").hidden = tfs.value !== "custom";
  atualizarBeInfo();
  if ((!store.get("tourVisto", false) && params.get("tour") !== "0") || params.get("tour") === "1") setTimeout(abrirTour, 600);
  if (DEMO) { iniciarDemo(); return; }
  mostrarVeredito(vereditoLocal("INICIO"));
  setTxt($("chipAtivo"), `${nomeAtivo(escolha.simbolo || "frxEURUSD")} · ${escolha.tf === "custom" ? escolha.custom : escolha.tf || "M5"}`);
  await carregarAtivos(escolha);
  if (params.has("auto")) conectar();   // ex.: /?auto
}
// gancho SÓ para os testes automáticos (/?teste=1): lê o estado e injeta mensagens como se viessem do servidor
if (params.get("teste") === "1") {
  window.farol = {
    estado: () => ({ sid: S.sid, simbolo: S.simbolo, tf: S.tf, seg: S.seg, barras: S.barras.map((b) => b.time),
                     ops: S.ops.map((o) => ({ ...o })), veredito: S.veredito && S.veredito.estado, descartadas: S.descartadas }),
    tratar: (m) => tratar(m),
  };
}
init();
})();
