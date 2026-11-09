#!/usr/bin/env python3
"""
Maestro v2.0 — Hybrid Cascade Router (Fast Heuristic + Semantic Vector + LLM Fallback).

Inspired by:
1. Aurelio Semantic Router & vLLM Semantic Router:
   - Sub-50ms vector space intent projection comparing user utterances against canonical route centroids
     using Cosine Similarity (via Ollama `nomic-embed-text:latest` + fast L2 Sparse N-Gram/BM25 projection).
2. RouteLLM (LMSYS) & LiteLLM Auto-Router v2:
   - Cascade confidence threshold calibration and Multi-Turn Session Affinity (sticky routing on short
     continuation turns to preserve context and avoid misrouting).
3. Earendil Works Pi (`virtual-models.md` & `jev-router.ts`):
   - Separation between virtual selection and physical dispatch with automatic `thinkingLevel`
     (`low` | `medium` | `high`) calibration based on task complexity.
"""

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# Canonical Routes in Maestro v2.0
ROUTE_AGY = "CIRURGIAO_AGY"
ROUTE_OPENCODE = "OPENCODE_WORKER"
ROUTE_RAG = "HOMELAB_RAG"
ROUTE_LOCAL_GPU = "WORKER_LOCAL_GPU"

# Canonical Intent Utterances (Exemplars for Semantic Vector Routing)
CANONICAL_ROUTE_UTTERANCES: Dict[str, List[str]] = {
    ROUTE_AGY: [
        "utilize o agy para revisar todos os repositorios do meu github e padronizar readme",
        "conecte via ssh no servidor omv ou labvm para diagnosticar containers docker e memoria swap",
        "abra uma issue com label agy:novo ou crie um pull request sincronizando omv-server-docs",
        "execute sudo agente-ler e sudo agente-docker para auditar volumes orfaos e fazer faxina no mergerfs",
        "homologue a stack do komodo ou immich na labvm por 60 segundos e atualize o relatorio para ia",
        "faça deploy gitops no komodo ou reinicie o servico no host debian trixie servidordokodak",
        "manda pro cirurgiao agy resolver o problema de disco fstab ou particao no servidor",
    ],
    ROUTE_OPENCODE: [
        "utilize o modelo deepseek ou opencode na nuvem para pesquisar no hugging face e reddit r/localllama",
        "qual o melhor modelo de linguagem para rodar em placa de video de 8gb vram comparando benchmarks",
        "analise profunda com contexto de 200k tokens sobre arquiteturas de agentes e papers recentes",
        "edite simultaneamente multiplos arquivos do projeto usando o agente opencode cli",
        "estou em modo jogo com a gpu ocupada no sunshine moonlight processe na nuvem deepseek flash",
        "faça uma pesquisa comparativa detalhada na internet sobre modelos quantizados q4_k_m vs moe",
    ],
    ROUTE_RAG: [
        "qual e o caminho canonico da pasta viva dos containers docker no servidor omv pool_koda",
        "quais sao as portas abertas e como funciona o protocolo ssap na smart tv lg kodachi webos",
        "explique a arquitetura dos pools mergerfs pool_koda e pool_cofre e quanto de ram e swap tem o omv",
        "quais stacks estao em producao no servidordokodak e qual a porta do jellyfin navidrome e immich",
        "como funciona o komodo gitops com ferretdb sqlite e a rede externa kodak-net no homelab",
        "quais sao os repositorios oficiais do ecossistema github kodak-ri e para que serve o tcc-bot",
    ],
    ROUTE_LOCAL_GPU: [
        "crie um script em python ou bash para monitorar uso de cpu e memoria com expressao regular",
        "escreva uma funcao em python puro para validar arquivos json e calcular hash sha256",
        "gere um dockerfile multi-stage otimizado com usuario nao-root para uma aplicacao flask gunicorn",
        "explique como funciona list comprehension, generators e async await em python 3",
        "escreva um comando awk ou sed para filtrar logs de erro e contar ocorrencias por minuto",
        "refatore este trecho de codigo c++ ou javascript para melhorar a performance e legibilidade",
    ],
}

# Weighted Trigger Rules for Stage 1 Fast Heuristic Gate
AGY_TRIGGERS = [
    "agy", "utilize o agy", "utilize agy", "chame o agy", "manda pro agy",
    "delegar pro agy", "cirurgiao agy", "cirurgião agy", "agente agy",
    "agente do omv", "ssh omv", "ssh labvm", "labvm", "sudo agente-ler",
    "sudo agente-docker", "swapfile", "aumentar swap", "particao", "partição",
    "fstab", "montar disco", "docker volume prune", "reboot", "reiniciar servidor",
    "libpam-systemd", "rrdcached", "mergerfs mount", "esteira ci", "abrir issue",
    "criar pr", "pull request", "pull requests", "homologar", "auditoria forense",
    "deploy-suite", "git push", "sincronizar repos", "revisar repos",
    "padronizar repos", "todos os repositorios", "todos os repositórios",
    "revisao em todas as repos", "revisão em todas as repos",
    "abrir uma issue", "abra uma issue", "abra issue", "crie uma issue", "crie issue",
    "criar uma issue", "abertura de issue", "abrir um pr", "abrir uma pr",
    "abra um pr", "abra uma pr", "crie um pr", "crie uma pr", "criar um pr", "criar uma pr",
    "suba a stack", "subir a stack", "suba o container", "subir o container",
    "reinicie o container", "reiniciar o container", "reinicie a stack", "reiniciar a stack",
    "docker restart", "docker stop", "docker logs", "docker up", "compose up",
    "verifique os logs", "verificar os logs", "logs do container", "derrube a stack",
]

AGY_ACTION_VERBS = [
    "revisar", "revisão", "revisao", "padronizar", "sincronizar", "atualizar",
    "criar", "publicar", "commitar", "auditar", "corrigir", "homologar",
    "instalar", "aplicar", "executar", "rodar", "verificar no servidor",
    "conferir no omv", "subir na labvm", "fazer deploy",
    "abrir", "abra", "abertura", "crie", "subir", "suba", "reiniciar", "reinicie",
    "restart", "parar", "pare", "derrubar", "derrube",
]

OPENCODE_TRIGGERS = [
    "deepseek", "opencode", "hugging face", "huggingface", "reddit",
    "locallm", "localllama", "r/locallm", "r/localllama", "nuvem", "cloud",
    "melhor modelo", "qual modelo", "comparar modelo", "comparar os modelos",
    "raciocinio profundo", "raciocínio profundo", "analise profunda",
    "análise profunda", "benchmarks", "200k", "modo jogo", "multiplos arquivos",
    "múltiplos arquivos", "pesquise", "pesquisar na web", "artigo cientifico",
]

RAG_TRIGGERS = [
    "omv", "servidordokodak", "mergerfs", "pool_koda", "pool_cofre",
    "kodak-net", "komodo", "ferretdb", "tv lg", "kodachi", "webos",
    "49uf6400", "ssap", "webkit", "upnp", "dial", "qbittorrent",
    "flaresolverr", "jellyfin", "navidrome", "immich", "tcc-bot", "romm",
    "homarr", "kodak-ri", "docker_data", "kodachi-ctl", "webos-mod-studio",
]

# Short continuation patterns for Session Affinity (LiteLLM v2 / Pi Virtual Models)
CONTINUATION_PREFIXES = (
    "e o ", "e a ", "e os ", "e as ", "todos os ", "todas as ",
    "tambem ", "também ", "agora ", "me mostre ", "mostre ",
    "continue", "faça isso", "pode fazer", "sim", "ok ", "isso mesmo",
)


def sparse_hashed_embedding(text: str, dims: int = 256) -> List[float]:
    """
    Ultra-fast (< 1ms) deterministic L2-normalized feature hashing vector projection
    combining word unigrams, word bigrams, and character 4-grams.
    Provides a zero-dependency semantic vector representation even when GPU/Ollama is offline.
    """
    vec = [0.0] * dims
    clean = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = [t for t in clean.split() if len(t) > 1]
    if not tokens:
        return vec

    # 1. Word unigrams (weight 2.0)
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
        idx = h % dims
        sign = 1.0 if (h & 1) == 0 else -1.0
        vec[idx] += sign * 2.0

        # 2. Character 4-grams for morphological resilience in PT-BR/EN (weight 0.8)
        if len(tok) >= 4:
            for i in range(len(tok) - 3):
                ngram = tok[i : i + 4]
                hn = int(hashlib.md5(ngram.encode("utf-8")).hexdigest()[:8], 16)
                vec[hn % dims] += (1.0 if (hn & 1) == 0 else -1.0) * 0.8

    # 3. Word bigrams (weight 2.5)
    for i in range(len(tokens) - 1):
        bg = f"{tokens[i]}_{tokens[i + 1]}"
        hb = int(hashlib.md5(bg.encode("utf-8")).hexdigest()[:8], 16)
        vec[hb % dims] += (1.0 if (hb & 1) == 0 else -1.0) * 2.5

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 1e-9:
        vec = [v / norm for v in vec]
    return vec


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    return dot / (n1 * n2)


def estimate_thinking_level(query: str, route: str, history_context: str = "") -> str:
    """
    Calibrates recommended thinking level ('low', 'medium', 'high') based on
    task complexity, risk surface, and route (inspired by RouteLLM & Pi Jev Router).
    """
    combined = f"{history_context} {query}".lower()

    high_markers = [
        "auditoria", "forense", "partição", "particao", "fstab", "prune",
        "revisão", "revisao", "padronizar", "todos os repositorios",
        "todos os repositórios", "arquitetura", "estudo profundo", "v2.0",
        "migração", "migracao", "multiplos", "múltiplos", "raciocinio",
        "raciocínio", "comparar", "benchmark", "segurança", "seguranca",
    ]
    medium_markers = [
        "ssh", "labvm", "omv", "komodo", "deploy", "stack", "compose",
        "container", "issue", "pull request", "github", "repositorio",
        "repositório", "swap", "memoria", "memória", "refatorar",
    ]

    if any(m in combined for m in high_markers) or len(query) > 320:
        return "high"
    if route in (ROUTE_AGY, ROUTE_OPENCODE) or any(m in combined for m in medium_markers):
        return "medium"
    return "low"


class HybridCascadeRouter:
    """
    3-Stage Hybrid Router for Maestro v2.0:
      Stage 1: Weighted Heuristic & Regex Gate + Session Affinity (< 1ms)
      Stage 2: Fast Semantic Vector Router (Ollama `nomic-embed-text:latest` + Sparse L2 Ensemble, < 45ms)
      Stage 3: Structured LLM JSON Classifier Fallback (`kodak-coder:latest`, only when ambiguous)
    """

    def __init__(
        self,
        ollama_base: str = "http://host.containers.internal:11434",
        llm_model: str = "kodak-coder:latest",
        embed_model: str = "nomic-embed-text:latest",
        enable_dense_embeddings: bool = True,
        enable_llm_fallback: bool = True,
    ):
        self.ollama_base = ollama_base.rstrip("/")
        self.llm_model = llm_model
        self.embed_model = embed_model
        self.enable_dense_embeddings = enable_dense_embeddings
        self.enable_llm_fallback = enable_llm_fallback

        # Precompute sparse embeddings for canonical utterances (< 2ms at init)
        self._sparse_prototypes: Dict[str, List[List[float]]] = {
            route: [sparse_hashed_embedding(u) for u in utterances]
            for route, utterances in CANONICAL_ROUTE_UTTERANCES.items()
        }
        self._dense_cache: Dict[str, List[float]] = {}
        self._ollama_online_cache: Optional[Tuple[float, bool]] = None

    def _is_ollama_online(self, ttl_sec: float = 5.0) -> bool:
        now = time.time()
        if self._ollama_online_cache and (now - self._ollama_online_cache[0]) < ttl_sec:
            return self._ollama_online_cache[1]
        try:
            req = urllib.request.Request(f"{self.ollama_base}/api/tags")
            with urllib.request.urlopen(req, timeout=0.45) as resp:
                ok = resp.status == 200
        except Exception:
            ok = False
        self._ollama_online_cache = (now, ok)
        return ok

    def _get_dense_embedding(self, text: str, timeout: float = 0.35) -> Optional[List[float]]:
        """Calls Ollama /api/embed (or /api/embeddings) for `nomic-embed-text:latest` with memory cache."""
        if not self.enable_dense_embeddings or not self._is_ollama_online():
            return None
        key = hashlib.md5(text.encode("utf-8")).hexdigest()
        if key in self._dense_cache:
            return self._dense_cache[key]

        try:
            payload = {"model": self.embed_model, "input": text}
            req = urllib.request.Request(
                f"{self.ollama_base}/api/embed",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                embeddings = data.get("embeddings")
                if embeddings and isinstance(embeddings, list) and len(embeddings) > 0:
                    vec = embeddings[0]
                    self._dense_cache[key] = vec
                    return vec
        except Exception:
            pass
        return None

    def _stage1_heuristic(
        self, query: str, history_context: str = "", last_route: Optional[str] = None
    ) -> Dict[str, Any]:
        """Stage 1: Weighted Heuristic & Regex Boundary Evaluation + Multi-Turn Session Affinity."""
        q_low = query.lower().strip()
        combined = f"{history_context} \n {query}".lower()

        scores: Dict[str, float] = {
            ROUTE_AGY: 0.0,
            ROUTE_OPENCODE: 0.0,
            ROUTE_RAG: 0.0,
            ROUTE_LOCAL_GPU: 0.15,  # base prior for general coding
        }
        matched_signals: Dict[str, List[str]] = {
            ROUTE_AGY: [],
            ROUTE_OPENCODE: [],
            ROUTE_RAG: [],
            ROUTE_LOCAL_GPU: [],
        }

        # 1. Check Explicit AGY & Infra Triggers (Highest Priority)
        for trig in AGY_TRIGGERS:
            pat = r"\b" + re.escape(trig) + r"\b"
            if re.search(pat, q_low):
                scores[ROUTE_AGY] += 0.90
                matched_signals[ROUTE_AGY].append(trig)
            elif re.search(pat, combined):
                scores[ROUTE_AGY] += 0.65
                matched_signals[ROUTE_AGY].append(f"hist:{trig}")

        # Check combination of GitHub/Repo/GitOps terms + Action Verbs -> CIRURGIAO_AGY
        if any(r in combined for r in ["github", "repositorio", "repositório", "repos", "repo", "issue", "issues", "pr", "prs"]):
            if any(v in combined for v in AGY_ACTION_VERBS):
                scores[ROUTE_AGY] += 0.85
                matched_signals[ROUTE_AGY].append("github+action_verb")

        # 2. Check Cloud / DeepSeek / OpenCode Research Triggers
        for trig in OPENCODE_TRIGGERS:
            if trig in q_low:
                scores[ROUTE_OPENCODE] += 0.85
                matched_signals[ROUTE_OPENCODE].append(trig)
            elif trig in combined:
                scores[ROUTE_OPENCODE] += 0.55
                matched_signals[ROUTE_OPENCODE].append(f"hist:{trig}")

        # Check if query contains infra mutation/management actions on homelab containers/stacks
        has_infra_action = any(
            v in q_low
            for v in [
                "suba", "subir", "reinicie", "reiniciar", "restart", "pare", "parar",
                "derrube", "derrubar", "logs", "corrija", "corrigir",
                "docker restart", "docker stop", "docker logs", "docker up",
                "compose up", "compose down", "compose restart",
            ]
        )
        if has_infra_action and any(t in q_low for t in RAG_TRIGGERS) and scores[ROUTE_AGY] < 0.80:
            scores[ROUTE_AGY] += 0.85
            matched_signals[ROUTE_AGY].append("infra_action_on_stack")

        # 3. Check Homelab RAG Triggers (only for informational queries, not active mutations)
        for trig in RAG_TRIGGERS:
            pat = r"\b" + re.escape(trig) + r"\b"
            if re.search(pat, q_low):
                if not has_infra_action:
                    scores[ROUTE_RAG] += 0.80
                    matched_signals[ROUTE_RAG].append(trig)
                else:
                    scores[ROUTE_RAG] += 0.20
                    matched_signals[ROUTE_RAG].append(f"infra_context:{trig}")
            elif re.search(pat, combined):
                scores[ROUTE_RAG] += 0.45
                matched_signals[ROUTE_RAG].append(f"hist:{trig}")

        # If both AGY and RAG triggered on the current query, executive AGY wins
        if scores[ROUTE_AGY] >= 0.80:
            scores[ROUTE_AGY] += 0.25

        # 4. Multi-Turn Session Affinity (Pi Virtual Models / LiteLLM Router v2 pattern)
        word_count = len(re.findall(r"\w+", q_low))
        is_short_followup = word_count <= 9 or q_low.startswith(CONTINUATION_PREFIXES)
        if is_short_followup and max(scores.values()) < 0.75:
            # Infer sticky route from history_context or last_route
            if last_route and last_route in scores:
                scores[last_route] += 0.70
                matched_signals[last_route].append(f"session_affinity:{last_route}")
            elif history_context:
                h_stage = self._stage1_heuristic(history_context, "", None)
                if h_stage["confidence"] >= 0.75:
                    inherited = h_stage["route"]
                    scores[inherited] += 0.75
                    matched_signals[inherited].append(f"multi_turn_inherit:{inherited}")

        best_route = max(scores.items(), key=lambda x: x[1])[0]
        best_score = min(1.0, scores[best_route])
        return {
            "route": best_route,
            "confidence": round(best_score, 3),
            "scores": {k: round(v, 3) for k, v in scores.items()},
            "signals": matched_signals[best_route],
        }

    def _stage2_semantic_vector(self, query: str) -> Dict[str, Any]:
        """
        Stage 2: Semantic Vector Similarity (Sparse L2 N-Gram/BM25 + Optional Dense Ollama Embedding).
        """
        q_sparse = sparse_hashed_embedding(query)
        sim_scores: Dict[str, float] = {}

        for route, proto_vecs in self._sparse_prototypes.items():
            max_sim = max(cosine_similarity(q_sparse, pv) for pv in proto_vecs)
            sim_scores[route] = round(max(0.0, max_sim), 4)

        engine_used = "sparse_l2_ngram_256d"
        # Optional dense boost with nomic-embed-text:latest if Ollama is online
        q_dense = self._get_dense_embedding(query, timeout=0.25)
        if q_dense is not None:
            engine_used = f"hybrid_ensemble({self.embed_model}+sparse_l2)"
            for route, utterances in CANONICAL_ROUTE_UTTERANCES.items():
                # Embed first 2 canonical prototypes per route (cached in RAM after first call)
                d_sims = []
                for u in utterances[:2]:
                    u_vec = self._get_dense_embedding(u, timeout=0.25)
                    if u_vec:
                        d_sims.append(cosine_similarity(q_dense, u_vec))
                if d_sims:
                    sim_scores[route] = round(0.6 * max(d_sims) + 0.4 * sim_scores[route], 4)

        best_route = max(sim_scores.items(), key=lambda x: x[1])[0]
        return {
            "route": best_route,
            "similarity": sim_scores[best_route],
            "all_similarities": sim_scores,
            "engine": engine_used,
        }

    def _stage3_llm_classifier(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Stage 3: Structured LLM Fallback (`kodak-coder:latest` JSON mode) when heuristic + semantic are ambiguous.
        """
        if not self.enable_llm_fallback or not self._is_ollama_online():
            return None

        prompt = (
            "Classifique o pedido do usuário em exatamente uma rota do ecossistema Homelab:\n"
            "- WORKER_LOCAL_GPU: código Python/Bash/Docker local, scripts, dúvidas gerais de programação.\n"
            "- HOMELAB_RAG: consultas sobre arquitetura do servidor OMV, MergerFS, Komodo ou Smart TV LG webOS.\n"
            "- OPENCODE_WORKER: pesquisa externa, DeepSeek nuvem, HuggingFace/Reddit, contexto 200k ou múltiplos arquivos.\n"
            "- CIRURGIAO_AGY: ações via SSH no OMV/labvm, diagnósticos ativos, git push/PR, governança de repositórios GitHub.\n\n"
            'Responda APENAS JSON válido: {"route": "...", "reason": "...", "thinking": "low|medium|high"}\n'
            f'Pedido: "{query}"'
        )
        payload = {
            "model": self.llm_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 120},
        }
        try:
            req = urllib.request.Request(
                f"{self.ollama_base}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                parsed = json.loads(raw.get("response", "{}"))
                r = parsed.get("route", ROUTE_LOCAL_GPU)
                if r in (ROUTE_AGY, ROUTE_OPENCODE, ROUTE_RAG, ROUTE_LOCAL_GPU):
                    return {
                        "route": r,
                        "reason": parsed.get("reason", "Classificado via LLM local."),
                        "thinking": parsed.get("thinking", "low"),
                    }
        except Exception:
            pass
        return None

    def route(
        self,
        query: str,
        history_context: str = "",
        last_route: Optional[str] = None,
        pipe_compat_cloud_name: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes the full 3-Stage Cascade Routing decision in < 50ms for 95%+ of requests.
        If `pipe_compat_cloud_name=True`, maps `OPENCODE_WORKER` to `OPENCODE_CLOUD` for
        100% backward compatibility with Open WebUI Pipe v1.4.
        """
        t0 = time.perf_counter()

        # Stage 1: Weighted Heuristic & Session Affinity (< 1ms)
        s1 = self._stage1_heuristic(query, history_context=history_context, last_route=last_route)

        # Stage 2: Semantic Vector Projection (< 15ms)
        s2 = self._stage2_semantic_vector(query)

        chosen_route = s1["route"]
        stage_decided = "STAGE_1_HEURISTIC"
        confidence = s1["confidence"]
        reason = ""

        if s1["confidence"] >= 0.70:
            chosen_route = s1["route"]
            stage_decided = "STAGE_1_HEURISTIC_FAST"
            sig_str = ", ".join(s1["signals"][:3]) if s1["signals"] else "regra ponderada"
            reason = self._build_reason(chosen_route, sig_str, stage_decided)
        elif s2["similarity"] >= 0.34:
            # Combine Stage 1 prior + Stage 2 semantic cosine similarity
            combined_scores: Dict[str, float] = {}
            for r in (ROUTE_AGY, ROUTE_OPENCODE, ROUTE_RAG, ROUTE_LOCAL_GPU):
                combined_scores[r] = 0.55 * s1["scores"].get(r, 0.0) + 0.85 * s2["all_similarities"].get(r, 0.0)
            chosen_route = max(combined_scores.items(), key=lambda x: x[1])[0]
            confidence = round(min(1.0, combined_scores[chosen_route]), 3)
            stage_decided = f"STAGE_2_SEMANTIC_VECTOR ({s2['engine']})"
            reason = self._build_reason(
                chosen_route, f"cos_sim={s2['all_similarities'][chosen_route]:.2f}", stage_decided
            )
        else:
            # Stage 3: LLM Classifier Fallback (if online) or default Local GPU Worker
            s3 = self._stage3_llm_classifier(query)
            if s3:
                chosen_route = s3["route"]
                stage_decided = "STAGE_3_LLM_STRUCTURED"
                confidence = 0.72
                reason = s3["reason"]
            else:
                chosen_route = ROUTE_LOCAL_GPU
                stage_decided = "STAGE_1_DEFAULT_CODING_PRIOR"
                confidence = 0.65
                reason = "Processamento local de código e engenharia na GPU RTX 3060 Ti (~70 tokens/s)."

        thinking = estimate_thinking_level(query, chosen_route, history_context=history_context)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        final_route = (
            "OPENCODE_CLOUD"
            if (pipe_compat_cloud_name and chosen_route == ROUTE_OPENCODE)
            else chosen_route
        )

        return {
            "route": final_route,
            "canonical_route": chosen_route,
            "thinking": thinking,
            "confidence": confidence,
            "stage": stage_decided,
            "latency_ms": latency_ms,
            "reason": reason,
            "telemetry": {
                "heuristic": s1,
                "semantic": s2,
            },
        }

    @staticmethod
    def _build_reason(route: str, signal_info: str, stage: str) -> str:
        if route == ROUTE_AGY:
            return f"Solicitação de automação / governança / AGY detectada ({signal_info}) [{stage}]."
        if route == ROUTE_OPENCODE:
            return f"Solicitação de pesquisa externa / inteligência avançada 200k detectada ({signal_info}) [{stage}]."
        if route == ROUTE_RAG:
            return f"Consulta contextual sobre a infraestrutura do Homelab ({signal_info}) [{stage}]."
        return f"Processamento local de código na GPU RTX 3060 Ti (~70 tokens/s) ({signal_info}) [{stage}]."
