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

// ================================================================== início
function iniciar() {
  if ($("cartaoAssistente")) iniciarAssistente();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
else iniciar();
})();
