/* Limiar · modo ao vivo.
   O navegador NÃO decide nada: o veredito (ENTRAR / SE PREPARANDO / AGUARDAR / CONFLITO / OBSERVAÇÃO)
   chega pronto do servidor (binarias/veredito.py), com probabilidade estimada, faixa, amostra e break-even.
   Aqui só desenhamos, atualizando apenas o que mudou. */
"use strict";

// ================================================================== utilidades
const $ = (id) => document.getElementById(id);
const el = (tag, cls, texto) => { const e = document.createElement(tag); if (cls) e.className = cls; if (texto !== undefined) e.textContent = texto; return e; };
const svgUso = (id, cls = "ic") => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("class", cls); s.setAttribute("aria-hidden", "true"); const u = document.createElementNS("http://www.w3.org/2000/svg", "use"); u.setAttribute("href", "#" + id); s.appendChild(u); return s; };
const store = {
  get(k, padrao) { try { const v = localStorage.getItem(k); return v === null ? padrao : JSON.parse(v); } catch { return padrao; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
const setTxt = (e, t) => { if (e && e.textContent !== t) e.textContent = t; };
const num = (v, casas = 2) => v === null || v === undefined ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
const pct = (v, casas = 0) => v === null || v === undefined ? "—" : num(100 * v, casas) + "%";
const comSinal = (v, casas = 2) => (v > 0 ? "+" : "") + num(v, casas);
const fmtHora = (t) => new Date(t * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
const FUSO = -new Date().getTimezoneOffset() * 60;   // gráfico em horário local
const ACAO = { CALL: "COMPRA", PUT: "VENDA" };
const ICONE_DIR = { CALL: "i-cima", PUT: "i-baixo" };
const css = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
const params = new URLSearchParams(location.search);
const DEMO = params.get("demo");

// ================================================================== estado da página
let CONFIG = null, ATIVOS = [], NOMES = {}, ws = null, conectado = false;
let ativas = new Set(), simboloAtual = null, tfAtual = "", casas = 5;
let fechaEm = null, offsetRelogio = 0, segVela = 60, janelaEntrada = 15;
let estadosEst = {}, RANKING = null, VEREDITO = null, ultimaAnalise = null;
let somLigado = store.get("som", true), volume = store.get("volume", 70);
let modoObs = store.get("observacao", false), mostrarTodos = store.get("todosSinais", false);
let modo = params.get("modo") || store.get("modo", "simples");

// ================================================================== gráfico (a página funciona mesmo sem ele)
let chart = null, serie = { setData() {}, update() {}, setMarkers() {}, applyOptions() {} };
let barras = [], sinaisMarcados = [], assinaturaMarcas = "";
try {
  chart = LightweightCharts.createChart($("grafico"), {
    autoSize: true,
    layout: { background: { type: "solid", color: css("--grafico-fundo") }, textColor: css("--grafico-texto"), fontSize: 12, fontFamily: css("--fonte-numero") },
    grid: { vertLines: { color: css("--grafico-grade") }, horzLines: { color: css("--grafico-grade") } },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.14, bottom: 0.08 } },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 8, barSpacing: 9 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal,
                 vertLine: { color: css("--linha-forte"), labelBackgroundColor: css("--superficie-3") },
                 horzLine: { color: css("--linha-forte"), labelBackgroundColor: css("--superficie-3") } },
  });
  serie = chart.addCandlestickSeries({ upColor: css("--alta"), downColor: css("--baixa"), borderVisible: false,
                                       wickUpColor: css("--alta"), wickDownColor: css("--baixa"), priceLineColor: css("--marca") });
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => posicionarLinhaEntrada());
} catch (e) {
  $("vazio").textContent = "Não foi possível carregar o gráfico (sem internet?). O resto da tela continua funcionando.";
}
const barra = (v) => ({ time: v[0] + FUSO, open: v[1], high: v[2], low: v[3], close: v[4] });

function atualizarBarra(v) {
  const b = barra(v), ult = barras[barras.length - 1];
  if (!ult || b.time > ult.time) { barras.push(b); serie.update(b); }
  else if (b.time === ult.time) { barras[barras.length - 1] = b; serie.update(b); }
  else {   // versão final de uma vela já ultrapassada: o gráfico não aceita update()
    const i = barras.findIndex((x) => x.time === b.time);
    if (i >= 0) { barras[i] = b; serie.setData(barras); assinaturaMarcas = ""; desenharMarcadores(); }
  }
}
function lider() { return (VEREDITO && VEREDITO.estrategia) || (RANKING && RANKING.melhor) || null; }
function desenharMarcadores() {
  if (!CONFIG) return;
  const sig = Object.fromEntries(CONFIG.estrategias.map((e) => [e.id, e.sigla]));
  const id = lider();
  const lista = sinaisMarcados.filter((s) => s.principal || s.id === id || (mostrarTodos && (modoObs || ativas.has(s.id))));
  const chave = `${id}|${mostrarTodos}|${lista.length}|${lista.length ? lista[lista.length - 1].t : 0}`;
  if (chave === assinaturaMarcas) return;
  assinaturaMarcas = chave;
  const alta = css("--alta"), baixa = css("--baixa"), neutro = css("--texto-3");
  const m = lista.map((s) => {
    const cor = s.principal || s.id === id ? (s.dir === "CALL" ? alta : baixa) : neutro;
    return { time: s.t + FUSO, position: s.dir === "CALL" ? "belowBar" : "aboveBar", color: cor,
             shape: s.dir === "CALL" ? "arrowUp" : "arrowDown", size: s.principal ? 1.6 : 1,
             text: s.principal ? "★" : (s.id === id ? "" : sig[s.id] || "") };
  }).sort((a, b) => a.time - b.time);
  serie.setMarkers(m);
}
function posicionarLinhaEntrada() {
  const linha = $("linhaEntrada");
  if (!chart || !barras.length || !fechaEm) { linha.hidden = true; return; }
  // logicalToCoordinate só aceita índices inteiros: fim da vela atual = centro dela + meio espaçamento
  const ts = chart.timeScale(), n = barras.length;
  const xUlt = ts.logicalToCoordinate(n - 1), xAnt = ts.logicalToCoordinate(n - 2);
  const largura = $("grafico").clientWidth - chart.priceScale("right").width();
  if (xUlt === null || xAnt === null) { linha.hidden = true; return; }
  const x = xUlt + (xUlt - xAnt) / 2;
  if (x < 0 || x > largura) { linha.hidden = true; return; }
  linha.hidden = false;
  linha.style.left = `${Math.round(x)}px`;
}

// ================================================================== sons, avisos e notificações
let actx = null;
function audio() {
  if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
  if (actx.state === "suspended") actx.resume();
  return actx;
}
function tom(freq, inicio, dur, tipo = "sine", vol = 0.18) {
  const ctx = audio(), t0 = ctx.currentTime + inicio, alvo = Math.max(0.0002, vol * (volume / 100));
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = tipo; o.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(alvo, t0 + 0.012);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g).connect(ctx.destination); o.start(t0); o.stop(t0 + dur + 0.03);
}
// `forcar`: toca mesmo com o som desligado (só o "Testar alertas" usa)
function somPreparo(forcar) { if (!somLigado && !forcar) return; try { tom(523, 0, 0.32, "sine", 0.13); tom(659, 0.22, 0.45, "sine", 0.11); } catch {} }
function somEntrada(dir, forcar) {
  if (!somLigado && !forcar) return;
  try {
    const base = dir === "PUT" ? 784 : 659, passo = dir === "PUT" ? 0.84 : 1.19;
    for (let i = 0; i < 3; i++) tom(base * Math.pow(passo, i), i * 0.13, 0.14, "triangle", 0.2);
    tom(base * Math.pow(passo, 3), 0.42, 0.42, "triangle", 0.2);
  } catch {}
}
function aviso(titulo, texto, tipo = "", icone = "i-sino", duracao = 8000) {
  const t = el("div", "aviso " + tipo);
  t.append(svgUso(icone), el("b", "", titulo), el("span", "", texto));
  $("toasts").prepend(t);
  setTimeout(() => t.remove(), duracao);
  while ($("toasts").children.length > 4) $("toasts").lastChild.remove();
}
function notificar(titulo, texto, forcar = false) {
  if (!("Notification" in window) || Notification.permission !== "granted" || (!document.hidden && !forcar)) return false;
  try { new Notification(titulo, { body: texto, tag: "limiar", silent: true }); return true; } catch { return false; }
}
const nomeAtivo = (s) => NOMES[s] || (s || "").replace(/^frx/, "").replace(/^([A-Z]{3})([A-Z]{3})$/, "$1/$2");

// ================================================================== dicas (tooltips "?")
const dica = $("dica");
let dicaAlvo = null;
function mostrarDica(alvo) {
  const texto = alvo.dataset.dica;
  if (!texto) return;
  dicaAlvo = alvo;
  dica.textContent = texto; dica.style.whiteSpace = "pre-line"; dica.hidden = false;
  const r = alvo.getBoundingClientRect(), d = dica.getBoundingClientRect();
  let x = r.left + r.width / 2 - d.width / 2, y = r.bottom + 8;
  if (y + d.height > innerHeight - 8) y = r.top - d.height - 8;
  x = Math.max(8, Math.min(innerWidth - d.width - 8, x));
  dica.style.left = `${x}px`; dica.style.top = `${Math.max(8, y)}px`;
}
function esconderDica() { dica.hidden = true; dicaAlvo = null; }
document.addEventListener("mouseover", (e) => { const a = e.target.closest("[data-dica]"); if (a && a !== dicaAlvo) mostrarDica(a); else if (!a && dicaAlvo) esconderDica(); });
document.addEventListener("focusin", (e) => { const a = e.target.closest("[data-dica]"); if (a) mostrarDica(a); });
document.addEventListener("focusout", esconderDica);
document.addEventListener("click", (e) => {
  const a = e.target.closest(".q[data-dica]");
  if (a) { e.preventDefault(); e.stopPropagation(); dicaAlvo === a ? esconderDica() : mostrarDica(a); }
  else if (dicaAlvo && !e.target.closest("[data-dica]")) esconderDica();
}, true);
addEventListener("scroll", esconderDica, { passive: true });

// ================================================================== faixa de probabilidade (IC + estimativa + break-even)
const DOMINIO = [0.30, 0.80];
const posicao = (v) => `${Math.max(0, Math.min(100, 100 * (v - DOMINIO[0]) / (DOMINIO[1] - DOMINIO[0])))}%`;
function desenharFaixa(caixa, p, grande = false) {
  if (!caixa._partes) {
    caixa.innerHTML = "";
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

// ================================================================== veredito
const ICONE_ESTADO = { ENTRAR: null, PREPARANDO: "i-ampulheta", AGUARDAR: "i-pausa", CONFLITO: "i-alerta",
                       OBSERVACAO: "i-olho", INICIO: "i-play", CARREGANDO: "i-ampulheta" };
let assinaturaVeredito = "";
function mostrarVeredito(v) {
  const chave = JSON.stringify(v) + simboloAtual + tfAtual;
  if (chave === assinaturaVeredito) return;
  assinaturaVeredito = chave;
  const card = $("veredito");
  const estadoAntes = card.dataset.estado;
  card.className = `veredito ${v.estado} ${v.estado === "ENTRAR" ? v.dir || "" : ""}`;
  card.dataset.estado = v.estado;
  if (estadoAntes !== v.estado) {   // reinicia a animação de entrada do conteúdo
    const corpo = card.querySelector(".v-corpo"); corpo.style.animation = "none"; void corpo.offsetWidth; corpo.style.animation = "";
  }
  setTxt($("vContexto"), simboloAtual ? `Agora · ${nomeAtivo(simboloAtual)} ${tfAtual}` : "Agora");
  const fita = $("vFita"); fita.hidden = !v.rotulo; setTxt(fita, v.rotulo || "");
  const icone = ICONE_ESTADO[v.estado] || ICONE_DIR[v.dir] || "i-pausa";
  const use = $("vIcone").querySelector("use"); if (use.getAttribute("href") !== "#" + icone) use.setAttribute("href", "#" + icone);
  setTxt($("vTitulo"), v.titulo);
  const dir = $("vDirecao");
  const mostraDir = v.dir && ["ENTRAR", "PREPARANDO", "OBSERVACAO"].includes(v.estado);
  dir.hidden = !mostraDir;
  if (mostraDir) {
    dir.className = `v-direcao ${v.dir} ${v.estado === "ENTRAR" ? "" : "contorno"}`;
    dir.replaceChildren(svgUso(ICONE_DIR[v.dir], ""), document.createTextNode(ACAO[v.dir]));
    dir.setAttribute("aria-label", `${ACAO[v.dir]}, ${v.dir === "CALL" ? "alta" : "baixa"}`);
  }
  $("vFrase").textContent = v.frase || "";
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
  atualizarRelogio();
  desenharMarcadores();
}
function vereditoLocal(estado) {
  if (estado === "INICIO") return { estado, titulo: "Escolha um ativo para começar",
    frase: "Toque em Conectar. O Limiar analisa o histórico e só sugere entrada quando uma estratégia tem vantagem comprovada." };
  return { estado: "CARREGANDO", titulo: "Analisando o histórico…",
    frase: "Carregando as velas e calculando todas as estratégias. Leva alguns segundos." };
}
function aplicarVeredito(v) {
  if (!v) return;
  VEREDITO = v;
  mostrarVeredito(v);
}
// Avisos decididos no servidor (binarias/avisos.py): aqui só tocamos o som e mostramos o texto.
const SONS = { formando: () => somPreparo(), entrada_call: () => somEntrada("CALL"), entrada_put: () => somEntrada("PUT"),
               resultado: () => somPreparo(), observacao: () => somPreparo() };
const ESTILO_AVISO = { formando: ["prep", "i-ampulheta"], entrada: [null, null], resultado: ["", "i-check"],
                       conflito: ["conf", "i-alerta"], lider: ["", "i-sino"], observacao: ["prep", "i-olho"] };
function mostrarAviso(a, forcar = false) {
  const [tipo, icone] = ESTILO_AVISO[a.categoria] || ["", "i-sino"];
  aviso(a.titulo, a.texto, tipo === null ? a.dir : tipo, icone || ICONE_DIR[a.dir] || "i-sino");
  if (a.som && SONS[a.som] && (somLigado || forcar)) SONS[a.som]();
  if (a.notificar) notificar(a.titulo, a.texto, forcar);
}

// ================================================================== relógio (anel + linha no gráfico)
const CIRC = 2 * Math.PI * 88;
function fmtTempo(s) {
  s = Math.max(0, Math.ceil(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60, p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`;
}
function atualizarRelogio() {
  const anel = $("anel"), prog = $("anelProgresso"), linha = $("linhaEntrada");
  if (!conectado || !fechaEm) {
    setTxt($("tempo"), "--:--"); setTxt($("tempoRotulo"), "vela fecha em");
    prog.style.strokeDashoffset = CIRC; linha.hidden = true; return;
  }
  let resta = fechaEm - (Date.now() / 1000 + offsetRelogio);
  while (resta < 0) resta += segVela;
  const estado = VEREDITO ? VEREDITO.estado : "";
  let tempo = resta, total = segVela, rotulo = "próxima vela em", chip = `próxima vela · ${fmtTempo(resta)}`;
  if (estado === "ENTRAR") {
    const restaEntrada = janelaEntrada - (segVela - resta);
    if (restaEntrada > 0) { tempo = restaEntrada; total = janelaEntrada; rotulo = "para entrar"; chip = `entrada aberta · ${fmtTempo(restaEntrada)}`; }
    else { rotulo = "vela fecha em"; }
  } else if (estado === "PREPARANDO") { rotulo = "confirmação em"; chip = `confirmação · ${fmtTempo(resta)}`; }
  setTxt($("tempo"), fmtTempo(tempo));
  setTxt($("tempoRotulo"), rotulo);
  prog.style.strokeDashoffset = String(CIRC * (1 - tempo / total));
  anel.classList.toggle("urgente", tempo <= Math.min(10, total * 0.25));
  anel.classList.toggle("pulso", estado === "ENTRAR");
  linha.className = "linha-entrada " + (estado === "ENTRAR" ? VEREDITO.dir : estado === "PREPARANDO" ? "PREPARANDO" : "");
  setTxt($("linhaEntradaTxt"), chip);
  posicionarLinhaEntrada();
}
setInterval(atualizarRelogio, 250);

// ================================================================== ranking visual
const linhasRk = {};
function porId(id) { return (CONFIG && CONFIG.estrategias.find((e) => e.id === id)) || { simples: "", descricao: "" }; }
function textoAgora(s) {
  if (!s || !s.dir) return "";
  if (s.estado === "SINAL") return ` · sinal agora: ${ACAO[s.dir]}`;
  return ` · ${s.cumpridas} de ${s.total} condições (${ACAO[s.dir]})`;
}
function aplicarRanking(r) {
  RANKING = r;
  setTxt($("rkSub"), `Acerto estimado nas últimas ${r.janela} velas. A faixa é a margem de erro; a linha é o mínimo para lucrar (${pct(r.break_even, 1)}).`);
  setTxt($("rkCriterio"), r.criterio);
  const lista = $("rkLista");
  if (lista.querySelector(".vazio-txt")) lista.replaceChildren();
  r.linhas.forEach((l, i) => {
    let item = linhasRk[l.id];
    if (!item) {
      item = { li: el("li", "rk-item") };
      const bt = el("button", "rk-linha"); bt.type = "button";
      item.pos = el("span", "rk-pos");
      const nome = el("span", "rk-nome"); item.nome = el("b"); item.info = el("small"); nome.append(item.nome, item.info);
      item.faixa = el("span", "faixa-prob"); item.pct = el("span", "rk-pct"); item.selo = el("span", "selo");
      bt.append(item.pos, nome, item.faixa, item.pct, item.selo);
      item.mais = el("div", "rk-mais"); item.maisTxt = el("p"); item.maisNum = el("p"); item.mais.append(item.maisTxt, item.maisNum);
      bt.addEventListener("click", () => { item.li.classList.toggle("aberto"); bt.setAttribute("aria-expanded", item.li.classList.contains("aberto")); });
      item.bt = bt;
      item.li.append(bt, item.mais);
      linhasRk[l.id] = item;
    }
    item.l = l;
    setTxt(item.pos, String(i + 1));
    setTxt(item.nome, l.nome);
    const j = l.janela, e = porId(l.id);
    item.li.classList.toggle("lider", i === 0 && !!j && j.vantagem);
    item.li.classList.toggle("desligada", !ativas.has(l.id));
    if (l.erro || !j) {
      setTxt(item.pct, "—"); setTxt(item.maisNum, "Erro ao calcular: " + (l.erro || "sem dados"));
    } else {
      desenharFaixa(item.faixa, { acerto: j.acerto, inf: j.ic_inf, sup: j.ic_sup, be: r.break_even });
      item.faixa.style.setProperty("--cor-faixa", j.vantagem ? css("--marca") : css("--texto-3"));
      setTxt(item.pct, pct(j.acerto));
      setTxt(item.maisNum, j.decididas
        ? `Deu ${j.operacoes} sinais nas últimas ${r.janela} velas. Acerto estimado ${pct(j.acerto)} (entre ${pct(j.ic_inf)} e ${pct(j.ic_sup)}), contra ${pct(r.break_even, 1)} necessários para lucrar.`
        : `Não deu nenhum sinal nas últimas ${r.janela} velas.`);
    }
    setTxt(item.maisTxt, e.simples || e.descricao);
    item.bt.dataset.dica = `${e.simples || e.descricao}\n${j ? `${j.operacoes} sinais nas últimas ${r.janela} velas.` : ""}`;
    const s = l.selo || { codigo: "poucos", texto: "Poucos dados" };
    item.selo.className = `selo ${s.codigo}`;
    setTxt(item.selo, s.texto + (s.codigo === "comprovada" && s.perdendo_forca ? " · perdendo força" : ""));
    atualizarInfoRk(item);
  });
  // reordena sem recriar (só se a ordem mudou)
  const ordem = r.linhas.map((l) => linhasRk[l.id].li);
  if (ordem.some((li, i) => lista.children[i] !== li)) ordem.forEach((li) => lista.appendChild(li));
  desenharTabelaRk(r);
  desenharMarcadores();
}
function atualizarInfoRk(item) {
  const j = item.l.janela, s = estadosEst[item.l.id];
  const base = j ? `${j.decididas} operações` : "sem dados";
  const txt = base + textoAgora(s) + (ativas.has(item.l.id) ? "" : " · desmarcada");
  if (item.info.textContent !== txt) {
    item.info.textContent = base;
    if (s && s.dir) { const a = el("span", `rk-agora ${s.estado === "SINAL" ? s.dir : ""}`, textoAgora(s)); item.info.appendChild(a); }
    if (!ativas.has(item.l.id)) item.info.append(" · desmarcada");
  }
}
function desenharTabelaRk(r) {
  const t = $("rkTabela"); t.replaceChildren();
  const cab = el("tr");
  ["Usar", "Estratégia", "Ops (janela)", "Acerto", "Margem de erro", "Lucro*", "Ops (histórico)", "Acerto hist.", "Força", "Selo"].forEach((h) => cab.appendChild(el("th", "", h)));
  t.appendChild(cab);
  for (const l of r.linhas) {
    const tr = el("tr"), j = l.janela || {}, h = l.historico || {};
    const cb = el("input"); cb.type = "checkbox"; cb.checked = ativas.has(l.id); cb.setAttribute("aria-label", `Usar ${l.nome}`);
    cb.addEventListener("change", () => alternar(l.id, cb.checked));
    const td0 = el("td"); td0.appendChild(cb); tr.appendChild(td0);
    [l.nome, j.operacoes ?? "—", pct(j.acerto, 1), j.ic_inf == null ? "—" : `${pct(j.ic_inf, 1)} a ${pct(j.ic_sup, 1)}`, num(j.lucro, 1),
     h.operacoes ?? "—", pct(h.acerto, 1), (l.forca || {}).estado || "—", (l.selo || {}).texto || "—"].forEach((v) => tr.appendChild(el("td", "", String(v))));
    t.appendChild(tr);
  }
}
function alternar(id, ligado) {
  ligado ? ativas.add(id) : ativas.delete(id);
  store.set("ativas", [...ativas]);
  enviar({ acao: "ativas", ativas: [...ativas] });
  if (RANKING) aplicarRanking(RANKING);
}

// ================================================================== estados por estratégia (a cada segundo)
function aplicarEstado(msg) {
  fechaEm = msg.fecha_em;
  offsetRelogio = msg.agora - Date.now() / 1000;
  estadosEst = Object.fromEntries(msg.estrategias.map((s) => [s.id, s]));
  for (const item of Object.values(linhasRk)) if (item.l) atualizarInfoRk(item);
  aplicarVeredito(msg.veredito);
}

// ================================================================== mercado
const NIVEL = { Fraca: 1, "Média": 2, Forte: 3, Calmo: 1, Normal: 2, Agitado: 3 };
function cartaoMercado(id, { classe = "", icone, valor, nivel, extra }) {
  const c = $(id);
  c.className = "m-cartao " + classe;
  const use = c.querySelector("use"); if (icone && use.getAttribute("href") !== "#" + icone) use.setAttribute("href", "#" + icone);
  setTxt(c.querySelector("b"), valor);
  const m = c.querySelector(".medidor"); if (m && nivel !== undefined) m.dataset.n = String(nivel);
  if (extra !== undefined) setTxt(c.querySelector(".m-extra"), extra);
}
function aplicarAnalise(a) {
  ultimaAnalise = a;
  setTxt($("mCriterio"), a.criterio || "");
  const h = a.humano || { ok: false, frase: `Análise indisponível: ${a.motivo || "sem dados"}.` };
  setTxt($("mFrase"), h.frase); setTxt($("resumoTexto"), h.frase);
  if (!h.ok) return;
  const classe = { SUBINDO: "ALTA", DESCENDO: "BAIXA", LATERAL: "" }[h.tendencia];
  cartaoMercado("mTend", { classe, icone: { SUBINDO: "i-cima", DESCENDO: "i-baixo", LATERAL: "i-lado" }[h.tendencia],
                           valor: h.tendencia, nivel: NIVEL[h.forca], extra: `força ${h.forca}` });
  cartaoMercado("mMov", { icone: "i-onda", valor: h.movimento, nivel: NIVEL[h.movimento],
                          extra: { Calmo: "pouca oscilação", Normal: "oscilação comum", Agitado: "oscilações grandes" }[h.movimento] });
  velaAtual(null);
  const dl = $("mTecnico"); dl.replaceChildren();
  const linha = (rotulo, valor, explica) => {
    const dt = el("dt", "", rotulo); const q = el("button", "q", "?"); q.type = "button"; q.dataset.dica = explica; dt.appendChild(q);
    dl.append(dt, el("dd", "", valor));
  };
  linha("Força (ADX 14)", `${num(a.adx, 1)} · ${a.forca}`, "O ADX mede a força do movimento, não a direção. Abaixo de 20 = fraca; de 20 a 25 = média; acima de 25 = forte.");
  linha("Preço × média de 50", `${comSinal(a.distancia_ma_atr)} ATR`, "Quanto o preço está acima (+) ou abaixo (−) da média das últimas 50 velas, medido em ATRs (o tamanho típico de uma vela).");
  linha("Inclinação da média", `${comSinal(a.inclinacao_atr)} ATR em 10 velas`, "Quanto a média de 50 velas subiu ou caiu nas últimas 10 velas. Acima de +0,5 ou abaixo de −0,5 indica tendência.");
  linha("Volatilidade (ATR 14)", `${num(a.atr, casas)} · percentil ${num(a.atr_percentil, 0)}`, "O ATR é o tamanho médio das velas. O percentil compara com as últimas 500 velas: perto de 50 é normal; acima de 90, muito agitado; abaixo de 10, muito parado.");
  linha("Resumo técnico", a.resumo || "—", "O mesmo resumo, com os números técnicos.");
}
function velaAtual(v) {
  if (!ultimaAnalise || !ultimaAnalise.ok) return;
  let dir;
  if (v) { const c = v[4] - v[1]; dir = c > 0 ? "ALTA" : c < 0 ? "BAIXA" : "DOJI"; }
  else dir = ultimaAnalise.vela_atual.direcao;
  cartaoMercado("mVela", { classe: dir === "DOJI" ? "" : dir, icone: dir === "ALTA" ? "i-cima" : dir === "BAIXA" ? "i-baixo" : "i-lado",
                           valor: { ALTA: "Subindo", BAIXA: "Descendo", DOJI: "Parada" }[dir], extra: v ? "em formação" : "" });
}

// ================================================================== top 3
let assinaturaTop = "";
function sparkline(valores) {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  s.setAttribute("class", "spark"); s.setAttribute("viewBox", "0 0 100 30"); s.setAttribute("preserveAspectRatio", "none"); s.setAttribute("aria-hidden", "true");
  if (!valores || valores.length < 2) return s;
  const min = Math.min(...valores), max = Math.max(...valores), amp = max - min || 1;
  const pts = valores.map((v, i) => [(100 * i) / (valores.length - 1), 27 - (24 * (v - min)) / amp]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("");
  const id = "g" + Math.random().toString(36).slice(2, 8);
  const defs = document.createElementNS(ns, "defs");
  defs.innerHTML = `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${css("--marca")}" stop-opacity=".35"/><stop offset="1" stop-color="${css("--marca")}" stop-opacity="0"/></linearGradient>`;
  const area = document.createElementNS(ns, "path"); area.setAttribute("d", `${d}L100,30L0,30Z`); area.setAttribute("fill", `url(#${id})`);
  const linha = document.createElementNS(ns, "path"); linha.setAttribute("d", d); linha.setAttribute("fill", "none");
  linha.setAttribute("stroke", css("--marca")); linha.setAttribute("stroke-width", "1.6"); linha.setAttribute("vector-effect", "non-scaling-stroke"); linha.setAttribute("stroke-linejoin", "round");
  s.append(defs, area, linha);
  return s;
}
function anelPontos(p) {
  const ns = "http://www.w3.org/2000/svg", c = 2 * Math.PI * 22;
  const caixa = el("div", "anel-pts");
  caixa.innerHTML = `<svg viewBox="0 0 52 52" aria-hidden="true"><circle class="t" cx="26" cy="26" r="22"/><circle class="p" cx="26" cy="26" r="22" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - p / 100)}"/></svg>`;
  caixa.appendChild(el("b", "", String(p)));
  caixa.setAttribute("role", "img"); caixa.setAttribute("aria-label", `Pontuação ${p} de 100`);
  void ns;
  return caixa;
}
function aplicarTop(msg) {
  setTxt($("topInfo"), `${msg.timeframe} · ${new Date(msg.atualizado * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}${msg.carregando ? ` · carregando ${msg.carregando}` : ""}`);
  $("qTop").dataset.dica = "Pontuação de 0 a 100:\n• " + msg.regra.join("\n• ");
  const chave = JSON.stringify(msg.itens.map((r) => [r.simbolo, r.pontos, r.porque, r.tendencia, (r.spark || []).slice(-1)[0]])) + msg.carregando;
  if (chave !== assinaturaTop) {
    assinaturaTop = chave;
    const lista = $("topLista"); lista.replaceChildren();
    if (!msg.itens.length) lista.appendChild(el("li", "vazio-txt", msg.carregando ? "Carregando históricos dos ativos…" : "Nenhum ativo aberto e com dados no momento."));
    msg.itens.forEach((r, i) => {
      const li = el("li", "top-item"); li.dataset.simbolo = r.simbolo; li.tabIndex = 0; li.setAttribute("role", "button");
      li.setAttribute("aria-label", `${i + 1}º ${nomeAtivo(r.simbolo)}, ${r.pontos} pontos. Abrir no gráfico.`);
      const nome = el("div", "top-nome"); nome.appendChild(el("b", "", nomeAtivo(r.simbolo)));
      const tag = el("span", "tag", "No gráfico"); tag.hidden = true; nome.appendChild(tag);
      const t = r.tendencia || "LATERAL";
      const tend = el("span", `tend ${t}`);
      tend.append(svgUso(t === "ALTA" ? "i-cima" : t === "BAIXA" ? "i-baixo" : "i-lado"), document.createTextNode({ ALTA: "Subindo", BAIXA: "Descendo", LATERAL: "Lateral" }[t]));
      const linha2 = el("div", "top-linha2"); linha2.append(tend, sparkline(r.spark));
      li.append(el("span", "top-pos", String(i + 1)), nome, anelPontos(r.pontos), linha2, el("div", "top-porque", r.porque || r.resumo || ""));
      const abrir = () => abrirAtivo(r.simbolo);
      li.addEventListener("click", abrir);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); } });
      lista.appendChild(li);
    });
  }
  marcarTopAtual();
  const tab = $("topTodos"); tab.replaceChildren();
  const cab = el("tr"); ["Ativo", "Pontos", "Movimento", "Tendência", "Estratégia", "Situação"].forEach((h) => cab.appendChild(el("th", "", h))); tab.appendChild(cab);
  for (const r of msg.todos) {
    const tr = el("tr"), c = r.componentes || {};
    [nomeAtivo(r.simbolo), r.pontos, c.volatilidade ?? "—", c.tendencia ?? "—", c.estrategia ?? "—",
     r.elegivel ? `${r.tendencia} · ADX ${num(r.adx, 0)}` : (r.motivo || "—")].forEach((v) => tr.appendChild(el("td", "", String(v))));
    tab.appendChild(tr);
  }
}
function marcarTopAtual() {
  for (const li of $("topLista").querySelectorAll(".top-item")) {
    const atual = li.dataset.simbolo === simboloAtual;
    li.classList.toggle("atual", atual);
    li.querySelector(".tag").hidden = !atual;
  }
}
function abrirAtivo(simbolo) {
  if (DEMO) { aviso("Demonstração", "Na demonstração o gráfico não troca de ativo. Ao vivo, isto abre o ativo sem recarregar a página.", "", "i-olho"); return; }
  const a = ATIVOS.find((x) => x.symbol === simbolo);
  if (a) { $("selMercado").value = a.market_display_name; preencherAtivos(); }
  else if (![...$("selAtivo").options].some((o) => o.value === simbolo)) $("selAtivo").add(new Option(simbolo, simbolo));
  $("selAtivo").value = simbolo;
  conectar();
}

// ================================================================== operações da sessão (bolinhas)
const bolinhas = {}, placar = { w: 0, l: 0 };
function adicionarSinal(msg) {
  const lista = $("bolinhas");
  if (lista.querySelector(".vazio-txt")) lista.replaceChildren();
  const b = el("li", "bolinha pend" + (msg.principal ? " principal" : ""));
  b.dataset.dica = `${fmtHora(msg.t + segVela)} · ${msg.nome}\n${ACAO[msg.dir]} ${msg.dir === "CALL" ? "▲" : "▼"} · ${nomeAtivo(msg.ativo)}\naguardando resultado`;
  b.setAttribute("aria-label", `${msg.nome}, ${ACAO[msg.dir]}, aguardando`);
  b.tabIndex = 0;
  lista.appendChild(b);
  bolinhas[msg.op] = { li: b, msg };
  while (lista.children.length > 40) lista.firstChild.remove();
}
function aplicarResultado(msg) {
  const x = bolinhas[msg.op];
  if (x) {
    const r = msg.resultado;
    x.li.className = `bolinha ${r}` + (x.msg.principal ? " principal" : "");
    x.li.replaceChildren(r === "WIN" ? svgUso("i-check") : r === "LOSS" ? svgUso("i-x") : document.createTextNode("="));
    const rotulo = { WIN: "acerto (WIN)", LOSS: "erro (LOSS)", EMPATE: "empate", CANCELADO: "cancelada" }[r] || r;
    x.li.dataset.dica = x.li.dataset.dica.replace("aguardando resultado", rotulo);
    x.li.setAttribute("aria-label", `${x.msg.nome}: ${rotulo}`);
  }
  if (msg.resultado === "WIN") placar.w++; else if (msg.resultado === "LOSS") placar.l++;
  setTxt($("placar"), `${placar.w} acerto${placar.w === 1 ? "" : "s"} · ${placar.l} erro${placar.l === 1 ? "" : "s"}`);
}

// ================================================================== conexão
const TEXTO_CONEXAO = { conectado: "Deriv conectada", conectando: "Conectando…", reconectando: "Reconectando…", desconectado: "Sem conexão" };
function setConexao(msg) {
  $("pontoDeriv").className = "ponto " + msg.estado;
  setTxt($("txtDeriv"), TEXTO_CONEXAO[msg.estado] || msg.texto);
  $("conexao").title = `${msg.texto}${msg.quedas ? ` · reconexões: ${msg.quedas}` : ""}`;
}
function setStatus(texto, nivel = "info") {
  $("conexao").dataset.status = texto;
  if (nivel === "erro") aviso("Atenção", texto, "erro", "i-alerta", 12000);
  else if (nivel === "aviso") aviso("Aviso", texto, "prep", "i-alerta", 10000);
}
function enviar(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
function abrirWs() {
  return new Promise((ok, falha) => {
    if (ws && ws.readyState === 1) return ok();
    const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws = sock;
    sock.onopen = () => ok();
    sock.onmessage = (ev) => { try { tratar(JSON.parse(ev.data)); } catch (e) { console.error("mensagem inválida", e); } };
    sock.onclose = () => {
      if (ws === sock) ws = null;
      falha(new Error("fechado"));
      if (conectado) {
        $("pontoDeriv").className = "ponto erro"; setTxt($("txtDeriv"), "Servidor local fora");
        setTimeout(() => conectado && conectar(), 3000);
      }
    };
  });
}
function tratar(msg) {
  switch (msg.tipo) {
    case "status": setStatus(msg.texto, msg.nivel); break;
    case "conexao": setConexao(msg); break;
    case "historico": {
      segVela = msg.seg; casas = msg.casas; simboloAtual = msg.simbolo; tfAtual = msg.timeframe;
      janelaEntrada = msg.janela_entrada || Math.min(60, Math.max(10, msg.seg * 0.25));
      serie.applyOptions({ priceFormat: { type: "price", precision: casas, minMove: Math.pow(10, -casas) } });
      barras = msg.velas.map(barra); serie.setData(barras);
      sinaisMarcados = msg.sinais; assinaturaMarcas = "";
      desenharMarcadores();
      if (chart) chart.timeScale().scrollToRealTime();
      $("vazio").hidden = !!chart;
      setTxt($("lgAtivo"), `${nomeAtivo(msg.simbolo)} · ${msg.timeframe}`);
      setTxt($("mAtivo"), `${nomeAtivo(msg.simbolo)} ${msg.timeframe}`);
      setTxt($("chipAtivo"), `${nomeAtivo(msg.simbolo)} · ${msg.timeframe}`);
      const ult = msg.velas[msg.velas.length - 1];
      if (ult) setTxt($("lgPreco"), ult[4].toFixed(casas));
      marcarTopAtual();
      break;
    }
    case "vela":
      atualizarBarra(msg.v);
      setTxt($("lgPreco"), msg.v[4].toFixed(casas));
      if (fechaEm && msg.v[0] + segVela >= fechaEm - 1) velaAtual(msg.v);
      break;
    case "estado": aplicarEstado(msg); break;
    case "ranking": aplicarRanking(msg); break;
    case "analise": aplicarAnalise(msg); break;
    case "decisao": aplicarVeredito(msg.veredito); break;
    case "aviso": mostrarAviso(msg); break;
    case "top3": aplicarTop(msg); break;
    case "sinal":
      sinaisMarcados.push({ t: msg.t, id: msg.id, dir: msg.dir, principal: msg.principal });
      desenharMarcadores();
      if (msg.registrado) adicionarSinal(msg);
      break;
    case "resultado": aplicarResultado(msg); break;
  }
}

// ================================================================== conectar / parar
function timeframeEscolhido() { return $("selTf").value === "custom" ? $("inpTfCustom").value.trim().toUpperCase() : $("selTf").value; }
function botaoConectar(ligado) {
  const b = $("btnConectar");
  b.classList.toggle("parar", ligado);
  b.querySelector("use").setAttribute("href", ligado ? "#i-stop" : "#i-play");
  setTxt(b.querySelector("span"), ligado ? "Parar" : "Conectar");
  b.setAttribute("aria-label", ligado ? "Parar" : "Conectar");   // no celular o botão mostra só o ícone
}
async function conectar() {
  const simbolo = $("selAtivo").value, tf = timeframeEscolhido();
  if (!simbolo || !tf) { $("dlgAtivo").showModal(); return; }
  try { audio(); } catch {}   // libera o áudio (precisa de um clique)
  const exp = Math.max(1, parseInt($("inpExp").value) || 1), payout = Math.min(500, Math.max(1, parseFloat($("inpPayout").value) || 85));
  store.set("escolha", { mercado: $("selMercado").value, simbolo, tf: $("selTf").value, custom: $("inpTfCustom").value, exp, payout });
  conectado = true; botaoConectar(true);
  VEREDITO = null;
  setTxt($("chipAtivo"), `${nomeAtivo(simbolo)} · ${tf}`);
  if (simbolo !== simboloAtual) { simboloAtual = simbolo; tfAtual = tf; }
  mostrarVeredito(vereditoLocal("CARREGANDO"));
  try { await abrirWs(); } catch { return; }
  enviar({ acao: "assinar", simbolo, timeframe: tf, expiracao: exp, payout, ativas: [...ativas], observacao: modoObs });
}
function parar() {
  conectado = false; botaoConectar(false);
  enviar({ acao: "parar" });
  fechaEm = null; VEREDITO = null;
  mostrarVeredito(vereditoLocal("INICIO"));
}
$("btnConectar").onclick = () => (conectado ? parar() : (DEMO ? null : conectar()));
$("vAcao").onclick = () => $("dlgAtivo").showModal();
$("btnAtivo").onclick = () => $("dlgAtivo").showModal();
$("dlgAtivo").addEventListener("close", () => { if ($("dlgAtivo").returnValue === "conectar" && !DEMO) conectar(); });
function atualizarBeInfo() {
  const p = Math.min(500, Math.max(1, parseFloat($("inpPayout").value) || 85)) / 100;
  setTxt($("beInfo"), `Com payout de ${num(p * 100, 0)}%, é preciso acertar mais de ${pct(1 / (1 + p), 1)} das operações só para empatar.`);
}
$("inpPayout").addEventListener("input", atualizarBeInfo);

// ================================================================== modos, observação e alertas
function aplicarModo() {
  document.body.classList.toggle("modo-simples", modo !== "detalhado");
  $("btnSimples").classList.toggle("on", modo !== "detalhado"); $("btnSimples").setAttribute("aria-pressed", modo !== "detalhado");
  $("btnDetalhado").classList.toggle("on", modo === "detalhado"); $("btnDetalhado").setAttribute("aria-pressed", modo === "detalhado");
}
$("btnSimples").onclick = () => { modo = "simples"; store.set("modo", modo); aplicarModo(); };
$("btnDetalhado").onclick = () => { modo = "detalhado"; store.set("modo", modo); aplicarModo(); };
function aplicarObs() {
  $("btnObs").setAttribute("aria-pressed", modoObs);
  $("btnObs").title = modoObs ? "Modo observação LIGADO: quando nada está comprovado, mostra a melhor candidata (não é recomendação)"
                              : "Modo observação: mostra a melhor candidata quando nenhuma estratégia está comprovada (não é recomendação)";
}
$("btnObs").onclick = () => {
  modoObs = !modoObs; store.set("observacao", modoObs); aplicarObs();
  if (DEMO) { if (DEMO === "aguardar" || DEMO === "observacao") irDemo(modoObs ? "observacao" : "aguardar"); return; }
  enviar({ observacao: modoObs });
  aviso(modoObs ? "Modo observação ligado" : "Modo observação desligado",
        modoObs ? "Quando nenhuma estratégia estiver comprovada, você verá a melhor candidata, marcada como NÃO COMPROVADA. Sem som de entrada."
                : "O veredito volta a mostrar só o que tem vantagem comprovada.", "", "i-olho");
};
$("chkTodos").checked = mostrarTodos;
$("chkTodos").onchange = () => { mostrarTodos = $("chkTodos").checked; store.set("todosSinais", mostrarTodos); desenharMarcadores(); };

function atualizarBotaoNotif() {
  const b = $("btnNotif");
  if (!("Notification" in window)) { b.textContent = "Sem notificações"; b.disabled = true; return; }
  b.textContent = Notification.permission === "granted" ? "Notificações permitidas" : Notification.permission === "denied" ? "Notificações bloqueadas" : "Permitir notificações";
  b.disabled = Notification.permission !== "default";
}
$("btnAlertas").onclick = () => { atualizarBotaoNotif(); $("dlgAlertas").showModal(); };
$("chkSom").checked = somLigado;
$("chkSom").onchange = () => { somLigado = $("chkSom").checked; store.set("som", somLigado); if (somLigado) somPreparo(); };
$("inpVolume").value = volume; setTxt($("volTxt"), `${volume}%`);
$("inpVolume").oninput = () => { volume = Number($("inpVolume").value); store.set("volume", volume); setTxt($("volTxt"), `${volume}%`); };
$("inpVolume").onchange = () => somPreparo(true);
$("btnNotif").onclick = async () => { if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission(); atualizarBotaoNotif(); };
$("btnTestar").onclick = async () => {
  const b = $("btnTestar"); b.disabled = true;
  try { audio(); } catch {}
  if ("Notification" in window && Notification.permission === "default") { try { await Notification.requestPermission(); } catch {} atualizarBotaoNotif(); }
  const espera = (ms) => new Promise((r) => setTimeout(r, ms));
  if (actx && actx.state !== "running") aviso("Áudio bloqueado", "O navegador bloqueou o som. Clique na página e tente de novo.", "erro", "i-alerta");
  if (!somLigado) aviso("Som desligado", "O teste toca mesmo assim, mas nos sinais reais você não ouviria nada.", "prep", "i-alerta", 10000);
  aviso("1 · Som de preparo", "Suave: toca quando aparece SE PREPARANDO.", "prep", "i-ampulheta", 6000);
  somPreparo(true); await espera(1500);
  aviso("2 · Som de entrada", "Toca no ENTRAR AGORA (COMPRA sobe o tom, VENDA desce).", "CALL", "i-cima", 6000);
  somEntrada("CALL", true); await espera(1500);
  if (!("Notification" in window)) aviso("3 · Notificação", "Este navegador não tem notificações.", "erro", "i-alerta", 10000);
  else if (Notification.permission === "granted") {
    notificar("Teste de alerta · Limiar", "Se você está vendo isto, as notificações funcionam.", true);
    aviso("3 · Notificação enviada", "Deve aparecer no canto da tela. Se não aparecer, confira o modo Não perturbe do sistema.", "", "i-sino", 10000);
  } else aviso("3 · Notificações bloqueadas", "Clique no cadeado ao lado do endereço e permita notificações.", "erro", "i-alerta", 12000);
  b.disabled = false;
};

// ================================================================== tour de primeira visita
const PASSOS = [
  { alvo: "veredito", titulo: "O veredito", texto: "Este cartão diz, em português simples, o que fazer agora: ENTRAR, SE PREPARANDO, AGUARDAR ou CONFLITO. ENTRAR só aparece quando uma estratégia tem vantagem comprovada no histórico, e sempre com a probabilidade estimada e a margem de erro." },
  { alvo: "grafico", titulo: "O gráfico", texto: "Velas ao vivo. A linha tracejada marca o fim da vela atual, com a contagem. As setas mostram só o sinal principal (★) e os sinais da estratégia líder." },
  { alvo: "top", titulo: "Top 3 ativos", texto: "Os ativos com o melhor cenário agora, com nota de 0 a 100 (o ? explica a regra). Toque em um para trocar o gráfico." },
  { alvo: "modos", titulo: "Simples ou Detalhado", texto: "No Detalhado você vê quem está acertando mais, o mercado em palavras simples e as suas operações. Em Alertas você testa o som. O botão ? reabre este guia." },
];
let passoTour = 0;
function abrirTour() { passoTour = 0; $("tour").hidden = false; mostrarPasso(); }
function fecharTour() { $("tour").hidden = true; store.set("tourVisto", true); }
function mostrarPasso() {
  const p = PASSOS[passoTour], alvo = document.querySelector(`[data-tour="${p.alvo}"]`);
  setTxt($("tourPasso"), `PASSO ${passoTour + 1} DE ${PASSOS.length} · COMO LER ESTA TELA`);
  setTxt($("tourTitulo"), p.titulo); setTxt($("tourTexto"), p.texto);
  $("tourVoltar").hidden = passoTour === 0;
  setTxt($("tourProximo"), passoTour === PASSOS.length - 1 ? "Entendi" : "Próximo");
  alvo.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  setTimeout(() => posicionarTour(alvo), 350);
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
$("btnTour").onclick = abrirTour;
$("tourPular").onclick = fecharTour;
$("tourVoltar").onclick = () => { passoTour = Math.max(0, passoTour - 1); mostrarPasso(); };
$("tourProximo").onclick = () => { if (passoTour >= PASSOS.length - 1) fecharTour(); else { passoTour++; mostrarPasso(); } };
addEventListener("resize", () => { if (!$("tour").hidden) posicionarTour(document.querySelector(`[data-tour="${PASSOS[passoTour].alvo}"]`)); posicionarLinhaEntrada(); });
addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("tour").hidden) fecharTour(); });

// ================================================================== demonstração (?demo=entrar)
const CENARIOS = { entrar: "Entrar", preparando: "Se preparando", aguardar: "Aguardar", conflito: "Conflito", observacao: "Observação" };
function irDemo(c) { const u = new URL(location.href); u.searchParams.set("demo", c); location.href = u.toString(); }
async function iniciarDemo() {
  $("faixaDemo").hidden = false;
  const nav = $("demoCenarios");
  for (const [c, nome] of Object.entries(CENARIOS)) {
    const a = el("a", c === DEMO ? "on" : "", nome); const u = new URL(location.href); u.searchParams.set("demo", c); a.href = u.toString(); nav.appendChild(a);
  }
  modoObs = DEMO === "observacao"; aplicarObs();
  conectado = true; botaoConectar(true);
  try {
    const msgs = await (await fetch(`/api/demo/${encodeURIComponent(DEMO)}`)).json();
    if (!Array.isArray(msgs)) throw new Error(msgs.erro || "cenário inválido");
    msgs.forEach(tratar);
  } catch (e) { aviso("Demonstração indisponível", String(e.message || e), "erro", "i-alerta"); }
}

// ================================================================== seletores e início
function preencherAtivos() {
  const lista = ATIVOS.filter((a) => a.market_display_name === $("selMercado").value);
  const sel = $("selAtivo"); sel.replaceChildren();
  let grupo = null, og = null;
  for (const a of lista) {
    if (a.submarket_display_name !== grupo) { grupo = a.submarket_display_name; og = document.createElement("optgroup"); og.label = grupo; sel.appendChild(og); }
    og.appendChild(new Option(`${a.display_name}${a.exchange_is_open ? "" : "  (fechado)"}`, a.symbol));
  }
}
async function init() {
  aplicarModo(); aplicarObs();
  CONFIG = await (await fetch("/api/config")).json();
  const salvas = store.get("ativas", null);
  ativas = new Set(salvas ? salvas.filter((id) => CONFIG.estrategias.some((e) => e.id === id)) : CONFIG.estrategias.map((e) => e.id));
  $("qTop").dataset.dica = "Pontuação de 0 a 100:\n• " + CONFIG.regra_scanner.join("\n• ");
  const tfs = $("selTf");
  for (const tf of CONFIG.timeframes) tfs.add(new Option(tf, tf));
  tfs.add(new Option("Personalizado…", "custom"));
  tfs.onchange = () => ($("campoTfCustom").hidden = tfs.value !== "custom");
  const escolha = store.get("escolha", { mercado: null, simbolo: "frxEURUSD", tf: "M5", custom: "", exp: 1, payout: 85 });
  tfs.value = escolha.tf || "M5"; $("inpTfCustom").value = escolha.custom || ""; $("inpExp").value = escolha.exp || 1;
  $("inpPayout").value = escolha.payout || Math.round(CONFIG.payout * 100);
  $("campoTfCustom").hidden = tfs.value !== "custom";
  atualizarBeInfo();
  if (!store.get("tourVisto", false) && params.get("tour") !== "0") setTimeout(abrirTour, 600);
  if (DEMO) { iniciarDemo(); return; }
  mostrarVeredito(vereditoLocal("INICIO"));
  setTxt($("chipAtivo"), `${nomeAtivo(escolha.simbolo || "frxEURUSD")} · ${escolha.tf === "custom" ? escolha.custom : escolha.tf || "M5"}`);
  try {
    const r = await fetch("/api/ativos");
    const dados = await r.json();
    if (!r.ok) throw new Error(dados.erro || r.status);
    ATIVOS = dados;
    NOMES = Object.fromEntries(ATIVOS.map((a) => [a.symbol, a.display_name]));
  } catch (e) {
    setStatus("Não foi possível listar os ativos da Deriv: " + e.message, "erro");
    $("selMercado").replaceChildren(new Option("—", ""));
    const sim = escolha.simbolo || "frxEURUSD";
    $("selAtivo").replaceChildren(new Option(sim, sim));
    return;
  }
  const mercados = [...new Set(ATIVOS.map((a) => a.market_display_name))];
  const selM = $("selMercado"); selM.replaceChildren();
  mercados.forEach((m) => selM.add(new Option(m, m)));
  const doSimbolo = ATIVOS.find((a) => a.symbol === escolha.simbolo);
  selM.value = doSimbolo ? doSimbolo.market_display_name : (escolha.mercado && mercados.includes(escolha.mercado) ? escolha.mercado : mercados[0]);
  preencherAtivos();
  if (doSimbolo) $("selAtivo").value = escolha.simbolo;
  selM.onchange = preencherAtivos;
  setTxt($("chipAtivo"), `${nomeAtivo($("selAtivo").value)} · ${timeframeEscolhido()}`);
  if (params.has("auto")) conectar();   // ex.: /?auto
}
init();
