/* Farol · escolha de tema (só visual: não mexe em sinais, vereditos nem no aviso de risco).
   Padrão / Natal / Automático (Natal de 1º/12 a 6/1). A escolha fica no navegador (localStorage) e vale na hora,
   sem recarregar. "Efeitos" liga/desliga luzes e neve; com prefers-reduced-motion nada se mexe.
   Carregado no <head> para aplicar o tema antes da primeira pintura (sem piscar o tema padrão). */
(function () {
  "use strict";
  const ESCOLHAS = ["padrao", "natal", "auto"];

  /** Natal de 1º de dezembro a 6 de janeiro (inclusive), no fuso do navegador. */
  function natalNaData(d) {
    const mes = d.getMonth() + 1, dia = d.getDate();
    return mes === 12 || (mes === 1 && dia <= 6);
  }
  /** Tema efetivo ("padrao" | "natal") a partir da escolha salva e da data. Escolha desconhecida = padrão. */
  function resolverTema(escolha, d) {
    if (escolha === "natal") return "natal";
    if (escolha === "auto") return natalNaData(d) ? "natal" : "padrao";
    return "padrao";
  }

  if (typeof module !== "undefined" && module.exports) {   // testes (node)
    module.exports = { natalNaData, resolverTema, ESCOLHAS };
    return;
  }

  const ler = (k, padrao) => { try { const v = localStorage.getItem(k); return v === null ? padrao : JSON.parse(v); } catch { return padrao; } };
  const gravar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sem armazenamento: só não lembra */ } };
  const params = new URLSearchParams(location.search);
  const raiz = document.documentElement;
  const estado = {
    escolha: params.get("tema") || ler("tema", "padrao"),
    efeitos: params.has("efeitos") ? params.get("efeitos") !== "0" : ler("efeitos", true),
  };
  if (!ESCOLHAS.includes(estado.escolha)) estado.escolha = "padrao";

  function trocarIcones(tema) {
    const svg = document.querySelector('link[rel="icon"][type="image/svg+xml"]');
    if (svg) svg.href = tema === "natal" ? "/static/marca/favicon-natal.svg" : "/static/marca/favicon.svg";
    const cor = document.querySelector('meta[name="theme-color"]');
    if (cor) cor.content = tema === "natal" ? "#070d1c" : "#09090f";
  }
  function aplicar() {
    const tema = resolverTema(estado.escolha, new Date());
    const mudou = raiz.dataset.tema !== tema;
    raiz.dataset.tema = tema;
    raiz.dataset.efeitos = estado.efeitos ? "on" : "off";
    trocarIcones(tema);
    const sel = document.getElementById("selTema");
    if (sel) sel.value = estado.escolha;
    const bt = document.getElementById("btnEfeitos");
    if (bt) { bt.hidden = tema !== "natal"; bt.setAttribute("aria-pressed", String(estado.efeitos)); }
    if (mudou) document.dispatchEvent(new CustomEvent("farol:tema", { detail: { tema } }));
  }
  aplicar();   // já no <head>

  function ligar() {
    const sel = document.getElementById("selTema"), bt = document.getElementById("btnEfeitos");
    if (sel) sel.addEventListener("change", () => { estado.escolha = sel.value; gravar("tema", estado.escolha); aplicar(); });
    if (bt) bt.addEventListener("click", () => { estado.efeitos = !estado.efeitos; gravar("efeitos", estado.efeitos); aplicar(); });
    aplicar();
    setInterval(aplicar, 60 * 60 * 1000);   // Automático vira sozinho se a página ficar aberta na virada do dia
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ligar);
  else ligar();
  window.farolTema = { natalNaData, resolverTema, aplicar, estado };
})();
