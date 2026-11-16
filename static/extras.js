/* Farol · extras do navegador: assistente (explica, não prevê), "Minha banca" (gestão de risco) e glossário.
   Nada aqui decide sinal. O assistente roda NO SERVIDOR (binarias/assistente.py); a banca usa contas do
   servidor (binarias/risco.py) e guarda os seus dados SÓ neste navegador. */
(() => {
"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, cls, texto) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (texto !== undefined) e.textContent = texto;
  return e;
};
const store = {
  get(k, padrao) { try { const v = localStorage.getItem(k); return v === null ? padrao : JSON.parse(v); } catch { return padrao; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sem armazenamento: só não lembra */ } },
};
const ponte = () => window.Farol || { enviar() {}, conectado: () => false, contexto: () => ({}), bloqueioDia() {} };

// ================================================================== assistente
const A = { status: null, esperando: false, timer: null };
const FONTE = {
  ia: "Explicação da IA (conferida pelo Farol)",
  desativado: "Explicação automática do Farol (sem IA)",
  descartada: "Explicação automática do Farol (a resposta da IA foi descartada)",
  erro: "Explicação automática do Farol (assistente indisponível)",
  limite: "Explicação automática do Farol (limite de chamadas atingido)",
  recusa: "Resposta padrão do Farol",
  sem_dados: "Farol",
};
function aplicarStatusAssistente(st) {
  if (!st) return;
  A.status = st;
  $("assistDesligado").hidden = !!st.ativo;
  $("assistStatus").textContent = st.ativo ? `IA ligada · ${st.restantes}/${st.limite_hora} por hora` : "IA desligada";
  $("assistStatus").title = st.ativo ? `Modelo: ${st.modelo}` : st.texto_desativado;
}
function pedirExplicacao(pergunta = "") {
  if (A.esperando) return;
  const f = ponte();
  if (!f.conectado()) {
    const texto = f.demo && f.demo()
      ? "Na demonstração (dados simulados) o assistente não é chamado. Conecte um ativo de verdade para usar."
      : "Conecte um ativo primeiro: o assistente só explica o que o Farol já calculou.";
    mostrarResposta({ fonte: "sem_dados", texto, aviso: "" });
    return;
  }
  A.esperando = true;
  $("btnExplicar").disabled = true; $("btnPerguntar").disabled = true;
  $("btnExplicar").textContent = "Pensando…";
  f.enviar({ acao: "explicar", pergunta });
  clearTimeout(A.timer);   // nunca trava: se o servidor não responder, libera os botões
  A.timer = setTimeout(() => {
    if (!A.esperando) return;
    terminar();
    mostrarResposta({ fonte: "erro", texto: "O assistente não respondeu a tempo. Tente de novo em instantes.", aviso: "" });
  }, 45000);
}
function terminar() {
  A.esperando = false;
  $("btnExplicar").disabled = false; $("btnPerguntar").disabled = false;
  $("btnExplicar").textContent = "Explique para mim";
}
function mostrarResposta(r) {
  $("assistResposta").hidden = false;
  $("assistResposta").className = `assist-resposta ${r.fonte || ""}`;
  $("assistFonte").textContent = (FONTE[r.fonte] || "Farol") + (r.cache ? " · já explicada nesta vela" : "") + (r.pergunta ? ` · “${r.pergunta}”` : "");
  $("assistTexto").textContent = r.texto || "";
  $("assistMotivo").hidden = !r.motivo; $("assistMotivo").textContent = r.motivo || "";
  $("assistAviso").textContent = r.aviso || "";
}
document.addEventListener("farol:assistente", (ev) => {
  terminar();
  mostrarResposta(ev.detail);
  aplicarStatusAssistente(ev.detail.status);
});
function iniciarAssistente() {
  $("btnExplicar").addEventListener("click", () => pedirExplicacao(""));
  $("formPergunta").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("inpPergunta").value.trim();
    if (q) pedirExplicacao(q);
  });
  for (const b of document.querySelectorAll(".chip-pergunta")) {
    b.addEventListener("click", () => { $("inpPergunta").value = b.textContent; pedirExplicacao(b.textContent); });
  }
  fetch("/api/assistente").then((r) => r.json()).then(aplicarStatusAssistente).catch(() => {});
}

// ================================================================== Minha banca (dados SÓ neste navegador)
const B = { cfg: null, diario: [], bloqueado: false, pedido: 0, t: null };
const brl = (v) => (v === null || v === undefined || Number.isNaN(v) ? "—"
  : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
const hoje = () => new Date().toLocaleDateString("sv-SE");   // AAAA-MM-DD no fuso local
const PADRAO_BANCA = { banca: 1000, pct: 1, perda: 5, parar: 3, meta: "", payout: 85 };
const CAMPOS = { banca: "bcBanca", pct: "bcPct", perda: "bcPerda", parar: "bcParar", meta: "bcMeta", payout: "bcPayout" };
const numero = (txt) => Number(String(txt || "").replace(",", "."));

function lerCampos() {
  const c = {};
  for (const [k, id] of Object.entries(CAMPOS)) {
    const v = $(id).value.trim();
    c[k] = v === "" ? (k === "meta" ? "" : PADRAO_BANCA[k]) : numero(v);
  }
  return c;
}
function lucroOp(o) { return o.resultado === "WIN" ? o.valor * o.payout : o.resultado === "LOSS" ? -o.valor : 0; }
function situacao() {
  const c = B.cfg;
  const total = B.diario.reduce((s, o) => s + lucroOp(o), 0);
  const deHoje = B.diario.filter((o) => o.data === hoje());
  const lucroHoje = deHoje.reduce((s, o) => s + lucroOp(o), 0);
  return { atual: c.banca + total, inicioDia: c.banca + total - lucroHoje, deHoje };
}
async function atualizarBanca() {
  B.cfg = lerCampos();
  store.set("farol.banca", B.cfg);
  const { atual, inicioDia, deHoje } = situacao();
  const n = ++B.pedido;
  let resp;
  try {
    const r = await fetch("/api/risco/dia", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ banca: atual, banca_inicio: inicioDia, pct: B.cfg.pct, perda_max_pct: B.cfg.perda,
                             parar_apos: B.cfg.parar, meta_pct: B.cfg.meta === "" ? null : B.cfg.meta,
                             operacoes: deHoje.map((o) => ({ resultado: o.resultado, valor: o.valor, payout: o.payout })) }),
    });
    resp = await r.json();
    if (!r.ok) throw new Error(resp.erro || "erro");
  } catch (e) {
    if (n !== B.pedido) return;
    $("bcAviso").hidden = false; $("bcAviso").className = "banca-aviso alto";
    $("bcAviso").textContent = `Não foi possível calcular: ${e.message}`;
    return;
  }
  if (n !== B.pedido) return;   // chegou uma resposta mais nova
  desenharBanca(resp, atual);
}
function desenharBanca({ entrada, dia }, atual) {
  $("bcEntrada").textContent = brl(entrada.valor);
  $("bcAtual").textContent = `Banca atual: ${brl(atual)} · ${entrada.pct.toLocaleString("pt-BR")}% por operação`;
  if (!$("bcValor").dataset.editado) $("bcValor").value = entrada.valor.toFixed(2);
  const av = entrada.avisos[0];
  $("bcAviso").hidden = !av;
  if (av) { $("bcAviso").className = `banca-aviso ${av.nivel}`; $("bcAviso").textContent = av.texto; }
  $("bcResultado").textContent = (dia.resultado > 0 ? "+" : "") + brl(dia.resultado);
  $("bcResultado").className = "numero " + (dia.resultado > 0 ? "pos" : dia.resultado < 0 ? "neg" : "");
  const usado = dia.limite_perda > 0 ? Math.min(100, Math.max(0, 100 * (dia.limite_perda - dia.distancia_limite) / dia.limite_perda)) : 0;
  $("bcBarra").style.setProperty("--usado", `${usado}%`);
  $("bcBarra").setAttribute("aria-valuenow", String(Math.round(usado)));
  $("bcBarra").classList.toggle("perto", usado >= 70);
  $("bcDistancia").textContent = dia.limite_perda > 0
    ? `Até o limite de perda do dia (${brl(dia.limite_perda)}): ${brl(dia.distancia_limite)}`
    : "Sem limite de perda do dia definido.";
  $("bcSeq").textContent = `${dia.operacoes} operação(ões) hoje: ${dia.wins} WIN, ${dia.losses} LOSS, ${dia.empates} empate(s). `
    + `Losses seguidos: ${dia.losses_seguidos}${B.cfg.parar ? ` de ${B.cfg.parar}` : ""}.`;
  $("bcMetaTxt").hidden = !dia.meta;
  if (dia.meta) {
    $("bcMetaTxt").textContent = dia.meta_atingida
      ? `Meta do dia (${brl(dia.meta)}) atingida. Parar agora protege o resultado.` : `Meta do dia: ${brl(dia.meta)}.`;
  }
  aplicarBloqueio(dia.bloqueado, dia.motivo);
  desenharDiario();
}
function aplicarBloqueio(ligado, motivo) {
  B.bloqueado = ligado;
  $("faixaBloqueio").hidden = !ligado;
  const m = ligado ? (motivo.match(/\((.*)\)/) || [])[1] : "";
  $("faixaBloqueioMotivo").textContent = m ? `Motivo: ${m}.` : "";
  $("cartaoBanca").classList.toggle("bloqueado", ligado);
  for (const b of document.querySelectorAll("#cartaoBanca [data-res]")) b.disabled = ligado;
  ponte().bloqueioDia(ligado);
}
function registrar(resultado) {
  const valor = numero($("bcValor").value);
  if (!(valor > 0)) { $("bcValor").focus(); return; }
  const ctx = ponte().contexto();
  B.diario.push({ t: Date.now(), data: hoje(), ativo: ctx.simbolo || "", tf: ctx.tf || "", resultado, valor,
                  payout: (B.cfg.payout || 85) / 100 });
  store.set("farol.diario", B.diario);
  delete $("bcValor").dataset.editado;
  atualizarBanca();
}
function desenharDiario() {
  const lista = $("bcLista"); lista.replaceChildren();
  const ultimas = B.diario.slice(-8).reverse();
  if (!ultimas.length) lista.appendChild(el("li", "vazio-txt", "Nenhuma operação registrada."));
  for (const o of ultimas) {
    const li = el("li", o.resultado);
    const quando = new Date(o.t).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    li.append(el("span", "", quando), el("span", "", o.ativo ? o.ativo.replace(/^frx/, "") : "—"),
              el("b", "", o.resultado), el("span", "numero", (lucroOp(o) >= 0 ? "+" : "") + brl(lucroOp(o))));
    lista.appendChild(li);
  }
  // curva da banca: banca inicial + resultado acumulado
  const pts = [B.cfg.banca];
  for (const o of B.diario) pts.push(pts[pts.length - 1] + lucroOp(o));
  const svg = $("bcCurva"); svg.replaceChildren();
  const NS = "http://www.w3.org/2000/svg";
  const min = Math.min(...pts), max = Math.max(...pts), faixa = max - min || 1;
  const x = (i) => (pts.length === 1 ? 150 : (i / (pts.length - 1)) * 296 + 2);
  const y = (v) => 104 - ((v - min) / faixa) * 96;
  const base = document.createElementNS(NS, "line");
  base.setAttribute("x1", "0"); base.setAttribute("x2", "300");
  base.setAttribute("y1", y(B.cfg.banca)); base.setAttribute("y2", y(B.cfg.banca));
  base.setAttribute("class", "cb-base"); svg.appendChild(base);
  const linha = document.createElementNS(NS, "polyline");
  linha.setAttribute("points", pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" "));
  linha.setAttribute("class", "cb-linha" + (pts[pts.length - 1] < B.cfg.banca ? " neg" : ""));
  svg.appendChild(linha);
  svg.setAttribute("aria-label", `Curva da banca: de ${brl(pts[0])} para ${brl(pts[pts.length - 1])} em ${B.diario.length} operações`);
}
function exportarCsv() {
  const cab = ["data_hora", "data", "ativo", "tempo", "resultado", "valor", "payout", "lucro"];
  const linhas = B.diario.map((o) => [new Date(o.t).toISOString(), o.data, o.ativo, o.tf, o.resultado,
    o.valor.toFixed(2), o.payout.toFixed(2), lucroOp(o).toFixed(2)].join(";"));
  const bom = String.fromCharCode(0xfeff);   // Excel reconhece UTF-8
  const blob = new Blob([bom + [cab.join(";"), ...linhas].join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = el("a"); a.href = URL.createObjectURL(blob); a.download = `farol-diario-${hoje()}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
async function simular() {
  const acerto = numero($("simAcerto").value) / 100;
  const caixa = $("simResultado"); caixa.hidden = false; caixa.textContent = "Simulando…";
  try {
    const r = await fetch("/api/risco/simular", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acerto, payout: (B.cfg.payout || 85) / 100, pct: B.cfg.pct, n_operacoes: Number($("simN").value) || 100 }),
    });
    const s = await r.json();
    if (!r.ok) throw new Error(s.erro);
    const pctBR = (v) => `${v > 0 ? "+" : ""}${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
    const reais = (v) => brl((B.cfg.banca * v) / 100);
    caixa.replaceChildren();
    caixa.className = "sim-resultado" + (s.abaixo_break_even ? " ruim" : "");
    const dl = el("dl");
    const linhas = [
      ["Break-even com este payout", `${(100 * s.break_even).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}% de acerto`],
      [`Resultado esperado em ${s.n_operacoes} operações`, `${pctBR(s.esperado_pct_banca)} da banca (${reais(s.esperado_pct_banca)})`],
      ["Metade das simulações terminou em", `${pctBR(s.mediana_final_pct)} ou menos`],
      ["90% das simulações ficaram entre", `${pctBR(s.p5_final_pct)} e ${pctBR(s.p95_final_pct)}`],
      ["Chance de terminar no prejuízo", `${Math.round(100 * s.prob_prejuizo)}%`],
      [`Chance de “ruína” (cair ${s.limite_ruina_pct}% ou mais)`, `${(100 * s.prob_ruina).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`],
    ];
    for (const [dt, dd] of linhas) dl.append(el("dt", "", dt), el("dd", "", dd));
    caixa.appendChild(dl);
    for (const a of s.avisos) caixa.appendChild(el("p", "sim-aviso", a));
    caixa.appendChild(el("p", "sub", s.explicacao));
  } catch (e) {
    caixa.textContent = `Não foi possível simular: ${e.message}`;
  }
}
function iniciarBanca() {
  const salvo = { ...PADRAO_BANCA, ...store.get("farol.banca", {}) };
  for (const [k, id] of Object.entries(CAMPOS)) {
    $(id).value = salvo[k];
    $(id).addEventListener("input", () => { clearTimeout(B.t); B.t = setTimeout(atualizarBanca, 250); });
  }
  B.diario = (store.get("farol.diario", []) || []).filter((o) => o && typeof o.valor === "number");
  $("bcValor").addEventListener("input", () => { $("bcValor").dataset.editado = "1"; });
  for (const b of document.querySelectorAll("#cartaoBanca [data-res]")) b.addEventListener("click", () => registrar(b.dataset.res));
  $("bcDesfazer").addEventListener("click", () => { B.diario.pop(); store.set("farol.diario", B.diario); atualizarBanca(); });
  $("bcCsv").addEventListener("click", exportarCsv);
  $("bcLimpar").addEventListener("click", () => {
    if (!B.diario.length || !confirm("Apagar todas as operações do diário deste navegador?")) return;
    B.diario = []; store.set("farol.diario", B.diario); atualizarBanca();
  });
  $("btnSimular").addEventListener("click", simular);
  // sugestão CONSERVADORA: o limite inferior da margem de erro da líder (pior caso plausível); sem líder, 50%
  $("bcSimulador").addEventListener("toggle", () => {
    if ($("simAcerto").value) return;
    const v = ponte().contexto().veredito;
    const inf = v && v.comprovada && v.prob && v.prob.inf;
    $("simAcerto").value = inf ? (100 * inf).toFixed(1) : "50";
    $("simDica").textContent = inf
      ? "Preenchido com o pior caso plausível da líder (limite inferior da margem de erro), não com a estimativa central."
      : "Sem estratégia comprovada: preenchido com 50% (acerto de quem chuta). Teste outros valores.";
  });
  atualizarBanca();
}

// ================================================================== modo educativo (glossário e silêncio)
const G = { termos: [], silencio: [], passo: 0, carregado: false };
function semAcento(t) { return t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
function desenharGlossario() {
  const filtro = semAcento($("inpGlossario").value.trim());
  const caixa = $("listaGlossario"); caixa.replaceChildren();
  const lista = G.termos.filter((t) => !filtro || semAcento(`${t.termo} ${t.texto}`).includes(filtro));
  if (!lista.length) caixa.appendChild(el("p", "vazio-txt", "Nenhum termo encontrado."));
  for (const t of lista) {
    const d = el("details", "g-termo");
    d.append(el("summary", "", t.termo), el("p", "", t.texto), el("p", "g-exemplo", `Exemplo: ${t.exemplo}`));
    if (filtro && lista.length <= 3) d.open = true;
    caixa.appendChild(d);
  }
}
function desenharSilencio() {
  const s = G.silencio[G.passo];
  if (!s) return;
  $("tsPasso").textContent = `${G.passo + 1} de ${G.silencio.length}`;
  $("tsTitulo").textContent = s.titulo;
  $("tsTexto").textContent = s.texto;
  const pontos = $("tsPontos"); pontos.replaceChildren();
  G.silencio.forEach((_, i) => pontos.appendChild(el("i", i === G.passo ? "on" : "")));
  $("tsAnterior").disabled = G.passo === 0;
  $("tsProximo").textContent = G.passo === G.silencio.length - 1 ? "Recomeçar" : "Próximo";
}
function abaAprender(qual) {
  const glos = qual === "glossario";
  $("abaGlossario").classList.toggle("on", glos); $("abaGlossario").setAttribute("aria-selected", String(glos));
  $("abaSilencio").classList.toggle("on", !glos); $("abaSilencio").setAttribute("aria-selected", String(!glos));
  $("painelGlossario").hidden = !glos; $("painelSilencio").hidden = glos;
}
async function abrirAprender(qual = "glossario") {
  abaAprender(qual);
  $("dlgAprender").showModal();
  if (G.carregado) return;
  try {
    const r = await (await fetch("/api/glossario")).json();
    G.termos = r.termos; G.silencio = r.silencio; G.carregado = true;
    desenharGlossario(); desenharSilencio();
  } catch {
    $("listaGlossario").replaceChildren(el("p", "vazio-txt", "Não foi possível carregar o glossário."));
  }
}
function iniciarAprender() {
  $("btnAprender").addEventListener("click", () => abrirAprender("glossario"));
  $("abaGlossario").addEventListener("click", () => abaAprender("glossario"));
  $("abaSilencio").addEventListener("click", () => abaAprender("silencio"));
  $("inpGlossario").addEventListener("input", desenharGlossario);
  $("tsAnterior").addEventListener("click", () => { G.passo = Math.max(0, G.passo - 1); desenharSilencio(); });
  $("tsProximo").addEventListener("click", () => { G.passo = (G.passo + 1) % G.silencio.length; desenharSilencio(); });
  // atalhos: /?aprender=glossario ou /?aprender=silencio (usado pelos screenshots)
  const q = new URLSearchParams(location.search).get("aprender");
  if (q) setTimeout(() => abrirAprender(q === "silencio" ? "silencio" : "glossario"), 300);
}

// ================================================================== início
function iniciar() {
  if ($("cartaoAssistente")) iniciarAssistente();
  if ($("cartaoBanca")) iniciarBanca();
  if ($("dlgAprender")) iniciarAprender();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
else iniciar();
})();
