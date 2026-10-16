#!/usr/bin/env python3
"""
Maestro v2.0 — Dual-System Hybrid Memory & Surgical Context Compression Engine.

Inspired by:
1. Tencent Hy-Memory 2.0 (Hy-Memory-30B-A3B):
   - Scene classification (chat / working / coding) with zero-LLM fast path.
   - Two-layer productivity memory: WorkingFact (session trace) + Experience (reusable solution).
   - Coordinate extraction over raw code dumping, plus Head+Tail truncation and LAST-5 turn window.
2. Earendil Works Pi (compaction.md & handoff.ts):
   - Context compaction with structured CompactionEntry (Goal, Key Decisions, Critical Context,
     cumulative <read-files> and <modified-files>) while keeping recent turns intact.
3. Microsoft LLMLingua / Optillm:
   - Token-budget-aware context compression scoring lines by technical coordinate entropy
     (canonical paths, ports, memory limits, container names, CLI flags) to eliminate token waste.
"""

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

# Default paths for persistent episodic memory and semantic RAG sources
DEFAULT_MEMORY_FILE = os.environ.get(
    "MAESTRO_MEMORY_FILE", "/work/automacao/.maestro_memory.json"
)

DEFAULT_RAG_DOCS = [
    "/work/DOCUMENTACAO_COMPLETA_OMV.md",
    "/work/omv-docs-repo/DOCUMENTACAO_COMPLETA_OMV.md",
    "/work/projetos-lab/RELATORIO_TV_LG_GEMINI.md",
    "/work/README.md",
]

STOP_WORDS = set(
    "o a os as um uma de do da dos das em no na nos nas por para com sem sob "
    "sobre e ou mas que se como qual quais sao são esta este esse essa isso "
    "isto tem ter foi ser era pelo pela pelos pelas muito mais seu sua seus "
    "suas quando onde quem voce você pra pro pros pras num numa uns umas the a "
    "an is of and in to for from with at by on".split()
)

# Curated resilient knowledge base (in-memory fallback when container lacks /work mounts)
HOMELAB_KNOWLEDGE_BASE: List[Dict[str, Any]] = [
    {
        "id": "github_kodak_ecosystem",
        "title": "Ecossistema Oficial de Repositórios GitHub (@Kodak-ri)",
        "keywords": [
            "github", "repositorio", "repositório", "repos", "repo",
            "kodak-ri", "git", "commit", "push", "pull request", "issue", "maestro",
        ],
        "content": (
            "Repositórios Oficiais (@Kodak-ri):\n"
            "1. Kodak-ri/maestro-orchestrator: Orquestrador Híbrido v2.0 (Roteador Semântico, Memória Híbrida Hy-Memory e Meta-Prompter AGY).\n"
            "2. Kodak-ri/omv-relatorios-agente: Diário de bordo, entregas (/work/entregas/), automação AGY Watcher e esteira CI.\n"
            "3. Kodak-ri/omv-server-docs: Fonte Única da Verdade GitOps do OMV 8.5 (DOCUMENTACAO_COMPLETA_OMV.md, docs/ e stacks-exemplo/).\n"
            "4. Kodak-ri/kodak-homelab-projects: Hardware Bazzite RTX 3060 Ti, modding Smart TV LG webOS (kodachi), Pocophone F1 e Archer C5.\n"
            "5. Kodak-ri/tcc-bot: Microsserviço ACH Heuer OSINT com cascata Gemini 2.5/2.0/1.5 e Gunicorn WSGI (porta 5051).\n"
            "6. Kodak-ri/steam-indie-deals: Radar automatizado de promoções Indie na Steam com alertas HTML por e-mail.\n"
            "7. Kodak-ri/RI-BOT & Kodak-ri/stack-arr-docs: Repositórios históricos padronizados."
        ),
    },
    {
        "id": "omv_storage_system",
        "title": "OpenMediaVault 8.5 & Storage Pools MergerFS",
        "keywords": [
            "omv", "servidordokodak", "mergerfs", "pool_koda", "pool_cofre",
            "armazenamento", "disco", "swap", "ram", "memoria", "docker_data",
        ],
        "content": (
            "Host OMV: servidordokodak (OpenMediaVault 8.5.11-1 sobre Debian 13.7 trixie).\n"
            "Recursos: CPU x86_64, 7.6 GiB RAM física + 4.0 GiB Swapfile ativo em /dev/sdb1.\n"
            "Pools MergerFS:\n"
            "- /srv/mergerfs/pool_koda (2.7 TB): mídias, ROMs e dados vivos de containers.\n"
            "- /srv/mergerfs/pool_cofre (916 GB): fotos pessoais e backups críticos (alta proteção).\n"
            "Caminho Canônico Vivo: /srv/mergerfs/pool_koda/docker_data/<stack>/ (proibido usar appdata/ ou /srv/dev-disk-by-uuid-*/)."
        ),
    },
    {
        "id": "docker_network_komodo",
        "title": "Docker Compose, Rede kodak-net & Komodo GitOps",
        "keywords": [
            "docker", "compose", "rede", "network", "kodak-net",
            "komodo", "gitops", "ferretdb", "deploy", "mem_limit",
        ],
        "content": (
            "Governança Docker & Komodo GitOps no OMV:\n"
            "- Rede externa obrigatória: networks: kodak-net (external: true). Proibido misturar com network_mode: bridge.\n"
            "- Limites obrigatórios: todo serviço deve declarar mem_limit e mem_reservation compatíveis com os 7.6 GiB do OMV.\n"
            "- Identidade estrita: todo Compose deve conter 'name: <PROJECT_NAME_REAL>' (media-stack, ts, romm-stack, tcc-bot, immich, komodo, jdownloader, management).\n"
            "- Komodo GitOps (http://<IP_SERVIDOR>:9120): FerretDB v1 (SQLite) + Core + Periphery (~25.13 MiB RAM total) sincronizado com Kodak-ri/omv-server-docs."
        ),
    },
    {
        "id": "active_stacks_omv",
        "title": "Stacks em Produção e Homologadas no OMV",
        "keywords": [
            "media", "qbittorrent", "flaresolverr", "jellyfin", "navidrome",
            "teamspeak", "ts", "tcc-bot", "immich", "jdownloader", "romm", "homarr",
        ],
        "content": (
            "Catálogo de Stacks OMV (/srv/mergerfs/pool_koda/docker_data/):\n"
            "1. media-stack: qBittorrent v5.2.4 (mem_limit: 2048m, libtorrent v2), FlareSolverr v3.5.2, Jellyfin (:8096), Navidrome (:4533), Prowlarr (:9696), Radarr (:7878), Sonarr (:8989).\n"
            "2. ts: TeamSpeak 6 Server (TSSERVER_LICENSE_ACCEPTED=accept, mem_limit: 512m).\n"
            "3. tcc-bot: Motor ACH OSINT (:5051, Gunicorn WSGI, non-root UID 10001, mem_limit: 512m).\n"
            "4. immich: Fotos (:2283, Postgres VectorChord 1024m, Server 1536m, ML 1536m, Valkey 256m).\n"
            "5. romm-stack: Emulação retrô (:8082, MariaDB, mem_limit: 1024m).\n"
            "6. management: Homarr Dashboard (:7575, mem_limit: 512m).\n"
            "7. jdownloader: JDownloader 2 (:5800, mem_limit: 1024m)."
        ),
    },
    {
        "id": "tv_lg_webos",
        "title": "Smart TV LG 49UF6400-SA (kodachi / webOS 4.1.0)",
        "keywords": [
            "tv", "lg", "kodachi", "webos", "49uf6400", "ssap",
            "websocket", "webkit", "upnp", "dial", "luna", "performance", "moonlight",
        ],
        "content": (
            "Smart TV LG 49UF6400-SA (hostname: kodachi, webOS 4.1.0 armv7l, IP <IP_LAN_TV>):\n"
            "- Portas ativas: 9922 (Dev Mode SSH), 3000/3001 (SSAP WebSocket), 9998 (WebKit Inspector), 36866 (DIAL REST), 1668 (UPnP DMR).\n"
            "- Arquitetura Anti-Brick: mods 100% em RAM (tmpfs /var/log, ZRAM 512MB, mount --bind sem escrita na eMMC).\n"
            "- Certificados SSL: overlay em /etc/ssl/certs/ca-certificates.crt (ISRG Root X1/X2 + DigiCert G2).\n"
            "- Utilitários Bazzite: /usr/local/bin/kodachi-ctl e /usr/local/bin/webos-mod-studio."
        ),
    },
    {
        "id": "bazzite_host_gpu",
        "title": "Host Bazzite Linux & NVIDIA RTX 3060 Ti (8 GB VRAM)",
        "keywords": [
            "bazzite", "gpu", "rtx", "3060", "nvidia", "ollama",
            "kodak-coder", "vram", "inferencia", "nomic-embed-text", "opencode",
        ],
        "content": (
            "Estação de IA Local (Host Bazzite Linux + GPU NVIDIA GeForce RTX 3060 Ti 8 GB GDDR6):\n"
            "- Endpoint Ollama: http://host.containers.internal:11434 (ou http://127.0.0.1:11434).\n"
            "- Modelos Locais: kodak-coder:latest (~70 tokens/s, ~4.7 GB VRAM), qwen2.5-coder:7b e nomic-embed-text:latest (768d embeddings).\n"
            "- Fallback Nuvem / Modo Jogo: opencode/deepseek-v4.1-flash-free (200k contexto) acionado automaticamente quando a GPU está dedicada a jogos (Sunshine/Moonlight)."
        ),
    },
]

# High-entropy technical coordinate patterns used by the LLMLingua-inspired compressor
COORDINATE_PATTERNS = [
    r"/srv/mergerfs/[a-zA-Z0-9_/-]+",
    r"/work/[a-zA-Z0-9_./-]+",
    r"/usr/local/bin/[a-zA-Z0-9_-]+",
    r"\b(?:kodak-net|pool_koda|pool_cofre|servidordokodak|labvm|kodachi|bazzite)\b",
    r"\b(?:mem_limit|mem_reservation|network_mode|external:\s*true)\b",
    r"\b(?:sudo\s+agente-ler|sudo\s+agente-docker|ssh\s+omv|ssh\s+labvm|kodachi-ctl)\b",
    r"\b(?:agy:novo|agy:trabalhando|agy:aguardando-deploy|agy:precisa-de-voce)\b",
    r"\bKodak-ri/[a-zA-Z0-9_-]+\b",
    r"\b\d+\s*(?:GiB|GB|MiB|MB|tokens/s|ms)\b",
    r":\d{4,5}\b",
]


def extract_technical_coordinates(text: str) -> List[str]:
    """Extracts unique canonical coordinates (paths, commands, repos, limits) from text."""
    found: List[str] = []
    seen = set()
    for pat in COORDINATE_PATTERNS:
        for match in re.findall(pat, text):
            clean = match.strip()
            if clean and clean not in seen:
                seen.add(clean)
                found.append(clean)
    return found


def classify_memory_scene(query: str) -> str:
    """
    Zero-LLM Scene Classifier inspired by Tencent Hy-Memory 2.0:
    Classifies input into 'coding', 'working' (infra/productivity/ops), or 'chat'.
    """
    q_low = query.lower()
    coding_markers = [
        "script", "python", "bash", "codigo", "código", "função", "funcao",
        "classe", "refator", "regex", "dockerfile", "yaml", "yml", "json",
        "bug", "erro de sintaxe", "compile", "test", "pytest", "c++", "js",
    ]
    working_markers = [
        "ssh", "omv", "labvm", "deploy", "komodo", "container", "stack",
        "mergerfs", "swap", "volume", "prune", "github", "repositório",
        "repositorio", "issue", "pull request", "agy", "auditoria", "relatorio",
    ]
    coding_hits = sum(1 for m in coding_markers if m in q_low)
    working_hits = sum(1 for m in working_markers if m in q_low)

    if working_hits > coding_hits and working_hits > 0:
        return "working"
    if coding_hits > 0:
        return "coding"
    return "chat"


def compress_context_for_token_budget(
    raw_text: str, query: str, max_chars: int = 1200
) -> Tuple[str, Dict[str, Any]]:
    """
    Token-Budget-Aware Context Compressor (inspired by LLMLingua + Hy-Memory Head/Tail & Coordinate Extraction).
    Scores each line by query-word overlap + technical coordinate entropy, pruning decorative fluff
    and preserving high-density lines in original document order.
    """
    if not raw_text or not raw_text.strip():
        return "", {"raw_chars": 0, "compressed_chars": 0, "compression_ratio": 0.0, "saved_pct": 0.0}

    raw_len = len(raw_text)
    query_words = [
        w.lower()
        for w in re.findall(r"\w+", query)
        if len(w) > 2 and w.lower() not in STOP_WORDS
    ]

    lines = raw_text.splitlines()
    scored_lines: List[Tuple[int, float, str]] = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip decorative markdown horizontal rules, HTML tags, or empty table separators
        if re.match(r"^[-=*_]{3,}$", stripped) or re.match(r"^\|[\s:|-]+\|$", stripped):
            continue
        if stripped.startswith(("<p ", "</p>", "<img ", "<a ", "</a", "<div", "</div")):
            continue

        # Normalize whitespace inside line
        compact_line = re.sub(r"\s+", " ", stripped)
        line_low = compact_line.lower()

        score = 1.0
        # 1. Header bonus (structural anchor)
        if compact_line.startswith("#"):
            score += 3.5

        # 2. Query keyword density
        for qw in query_words:
            if qw in line_low:
                score += 4.0

        # 3. Technical coordinate density (LLMLingua high-perplexity / Hy-Memory coordinate priority)
        coords = extract_technical_coordinates(compact_line)
        score += len(coords) * 3.0

        # 4. Head+Tail position bonus (Hy-Memory preserves head and tail context)
        if idx < 3 or idx >= max(len(lines) - 2, 3):
            score += 1.5

        # Normalize slightly by length to favor concise, high-entropy facts
        density = score / max(len(compact_line) / 60.0, 0.8)
        scored_lines.append((idx, density, compact_line))

    if not scored_lines:
        trimmed = raw_text.strip()[:max_chars]
        return trimmed, {
            "raw_chars": raw_len,
            "compressed_chars": len(trimmed),
            "compression_ratio": round(len(trimmed) / max(raw_len, 1), 3),
            "saved_pct": round((1.0 - len(trimmed) / max(raw_len, 1)) * 100, 1),
        }

    # Select highest density lines until max_chars budget is filled
    by_density = sorted(scored_lines, key=lambda x: x[1], reverse=True)
    selected_indices = set()
    current_chars = 0

    for idx, _density, text_line in by_density:
        line_cost = len(text_line) + 1
        if current_chars + line_cost > max_chars:
            continue
        selected_indices.add(idx)
        current_chars += line_cost

    # Reconstruct in original document order for coherent reading
    ordered_lines = [
        text_line for idx, _d, text_line in scored_lines if idx in selected_indices
    ]
    compressed = "\n".join(ordered_lines)
    comp_len = len(compressed)
    saved_pct = round(max(0.0, (1.0 - comp_len / max(raw_len, 1)) * 100.0), 1)

    metrics = {
        "raw_chars": raw_len,
        "compressed_chars": comp_len,
        "raw_est_tokens": max(1, raw_len // 4),
        "compressed_est_tokens": max(1, comp_len // 4),
        "compression_ratio": round(comp_len / max(raw_len, 1), 3),
        "saved_pct": saved_pct,
    }
    return compressed, metrics


class HybridMemoryManager:
    """
    Two-Way Hybrid Memory System:
    1. Short-Term / Episodic & Working Memory (WorkingFact + Reusable Experience + Pi Compaction)
    2. Long-Term / Semantic Homelab RAG with Surgical Token-Budget Compression
    """

    def __init__(
        self,
        memory_file: str = DEFAULT_MEMORY_FILE,
        rag_docs: Optional[List[str]] = None,
        max_episodic_turns: int = 20,
        inject_recent_turns: int = 5,
    ):
        self.memory_file = memory_file
        self.rag_docs = rag_docs if rag_docs is not None else list(DEFAULT_RAG_DOCS)
        self.max_episodic_turns = max_episodic_turns
        self.inject_recent_turns = inject_recent_turns
        self.state = self._load_state()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": "2.0.0",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "compaction_summary": "",
            "compactions_count": 0,
            "cumulative_files": [],
            "working_facts": [],
            "experiences": [
                {
                    "id": "exp_omv_gitops_stack",
                    "task_pattern": "Criar ou ajustar stack Docker Compose para o OMV (servidordokodak)",
                    "search_keys": ["compose", "stack", "omv", "komodo", "mem_limit", "kodak-net"],
                    "solution": (
                        "Declarar 'name: <PROJECT_NAME>' idêntico à produção, usar '/srv/mergerfs/pool_koda/docker_data/<stack>', "
                        "rede externa 'kodak-net', definir 'mem_limit'/'mem_reservation' para os 7.6 GiB de RAM do OMV e validar na labvm por 60s."
                    ),
                    "boundary_envs": ["Debian 13", "OMV 8.5", "Komodo GitOps"],
                    "confidence": 0.98,
                },
                {
                    "id": "exp_webos_ram_overlay",
                    "task_pattern": "Otimizar performance ou aplicar mod na Smart TV LG 49UF6400-SA (kodachi)",
                    "search_keys": ["tv", "lg", "kodachi", "webos", "ssap", "overlay", "ssl"],
                    "solution": (
                        "Executar modificações 100% em RAM (tmpfs /var/log, ZRAM 512MB e mount --bind) via kodachi-ctl na porta SSH 9922 "
                        "ou WebSocket SSAP 3000/3001, sem gravar na flash eMMC."
                    ),
                    "boundary_envs": ["webOS 4.1.0 armv7l", "LG 49UF6400-SA"],
                    "confidence": 0.96,
                },
                {
                    "id": "exp_github_sanitization",
                    "task_pattern": "Publicar, revisar ou sincronizar repositórios GitHub @Kodak-ri",
                    "search_keys": ["github", "repositorio", "repositório", "commit", "push", "sanitizar"],
                    "solution": (
                        "Substituir todos os IPs reais, senhas e tokens por placeholders (<IP_LAN>, <IP_SERVIDOR>, <SENHA>, <TOKEN>), "
                        "validar com grep -E antes do commit e atualizar STATUS_PROPOSTAS.md e README.md."
                    ),
                    "boundary_envs": ["GitHub @Kodak-ri", "CI Anti-Leak"],
                    "confidence": 0.99,
                },
            ],
        }

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "working_facts" in data:
                    return data
            except Exception:
                pass
        return self._default_state()

    def save_state(self) -> None:
        self.state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            parent = os.path.dirname(self.memory_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def record_turn(
        self,
        query: str,
        route: str,
        thinking: str,
        reason: str,
        sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Records a WorkingFact (Hy-Memory style) and triggers automatic Pi-style
        compaction if working_facts exceeds max_episodic_turns.
        """
        scene = classify_memory_scene(query)
        coords = extract_technical_coordinates(query)
        fact_id = "fact_" + hashlib.sha1(f"{time.time()}:{query}".encode("utf-8")).hexdigest()[:8]

        fact = {
            "id": fact_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scene": scene,
            "query": query[:300],
            "route": route,
            "thinking": thinking,
            "reason": reason[:160],
            "coordinates": coords[:8],
            "sources": (sources or [])[:4],
        }

        self.state["working_facts"].append(fact)

        # Accumulate tracked files/paths (Pi cumulative file tracking)
        for c in coords:
            if c.startswith("/") and c not in self.state["cumulative_files"]:
                self.state["cumulative_files"].append(c)

        if len(self.state["working_facts"]) > self.max_episodic_turns:
            self.compact_episodic_memory(keep_recent=self.inject_recent_turns)
        else:
            self.save_state()

        return fact

    def compact_episodic_memory(self, keep_recent: int = 5) -> Dict[str, Any]:
        """
        Pi-inspired Compaction: summarizes older WorkingFacts into a structured
        compaction_summary while preserving the most recent `keep_recent` entries.
        """
        facts = self.state.get("working_facts", [])
        if len(facts) <= keep_recent:
            return {
                "compacted": False,
                "kept_facts": len(facts),
                "summary": self.state.get("compaction_summary", ""),
            }

        to_summarize = facts[:-keep_recent]
        kept = facts[-keep_recent:]

        routes_count: Dict[str, int] = {}
        scenes_count: Dict[str, int] = {}
        topics: List[str] = []
        for f in to_summarize:
            r = f.get("route", "UNKNOWN")
            s = f.get("scene", "chat")
            routes_count[r] = routes_count.get(r, 0) + 1
            scenes_count[s] = scenes_count.get(s, 0) + 1
            q_short = f.get("query", "").strip()
            if q_short and len(topics) < 5:
                topics.append(q_short[:80])

        prev_summary = self.state.get("compaction_summary", "").strip()
        routes_str = ", ".join(f"{k}:{v}" for k, v in routes_count.items())
        files_str = ", ".join(self.state.get("cumulative_files", [])[-8:]) or "Nenhum arquivo rastreado"

        new_summary_block = (
            f"[Compactação #{self.state.get('compactions_count', 0) + 1} | {len(to_summarize)} turnos arquivados | "
            f"Rotas: {routes_str} | Coordenadas: {files_str} | Tópicos: {' ; '.join(topics[:3])}]"
        )
        if prev_summary:
            combined = f"{prev_summary}\n{new_summary_block}"
            # Keep summary bounded
            self.state["compaction_summary"] = combined[-1200:]
        else:
            self.state["compaction_summary"] = new_summary_block

        self.state["compactions_count"] = self.state.get("compactions_count", 0) + 1
        self.state["working_facts"] = kept
        self.save_state()

        return {
            "compacted": True,
            "archived_count": len(to_summarize),
            "kept_facts": len(kept),
            "summary": self.state["compaction_summary"],
        }

    def get_episodic_context(self, query: str, max_turns: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves the LAST N USER TURNS (WorkingFacts) + matching reusable Experiences
        (Hy-Memory Working/Coding retrieval).
        """
        limit = max_turns if max_turns is not None else self.inject_recent_turns
        recent_facts = self.state.get("working_facts", [])[-limit:]

        q_words = set(
            w.lower()
            for w in re.findall(r"\w+", query)
            if len(w) > 2 and w.lower() not in STOP_WORDS
        )

        matched_experiences = []
        for exp in self.state.get("experiences", []):
            hits = sum(
                1
                for kw in exp.get("search_keys", [])
                if kw in query.lower() or any(w in kw for w in q_words)
            )
            if hits > 0:
                matched_experiences.append((hits * exp.get("confidence", 1.0), exp))

        matched_experiences.sort(key=lambda x: x[0], reverse=True)
        top_experiences = [item[1] for item in matched_experiences[:2]]

        return {
            "compaction_summary": self.state.get("compaction_summary", ""),
            "recent_facts": recent_facts,
            "experiences": top_experiences,
            "last_route": recent_facts[-1]["route"] if recent_facts else None,
            "last_thinking": recent_facts[-1]["thinking"] if recent_facts else None,
        }

    def retrieve_semantic_rag(
        self, query: str, max_sections: int = 2, max_chars_budget: int = 1500
    ) -> Dict[str, Any]:
        """
        Retrieves Long-Term Semantic Memory from local Homelab Markdown docs +
        Curated Knowledge Base, and compresses snippets using LLMLingua-style
        coordinate-density compression.
        """
        words = [
            w.lower()
            for w in re.findall(r"\w+", query)
            if len(w) > 2 and w.lower() not in STOP_WORDS
        ]
        if not words:
            return {"sections": [], "compressed_text": "", "sources": [], "metrics": {}}

        scored_candidates: List[Dict[str, Any]] = []
        visited_realpaths = set()

        # 1. Scan Markdown documentation files on disk
        for doc_path in self.rag_docs:
            if not os.path.exists(doc_path):
                continue
            real_p = os.path.realpath(doc_path)
            if real_p in visited_realpaths:
                continue
            visited_realpaths.add(real_p)

            try:
                with open(doc_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                current_title = os.path.basename(doc_path)
                current_lines: List[str] = []
                for line in text.splitlines():
                    if re.match(r"^#{1,3}\s+", line):
                        if current_lines:
                            sec_body = "\n".join(current_lines)
                            sc = self._score_text_section(words, current_title, sec_body)
                            if sc > 0:
                                scored_candidates.append({
                                    "score": sc,
                                    "file": os.path.basename(doc_path),
                                    "path": doc_path,
                                    "title": current_title,
                                    "raw_content": sec_body[:2400],
                                })
                            current_lines = []
                        current_title = line.strip()
                    current_lines.append(line)
                if current_lines:
                    sec_body = "\n".join(current_lines)
                    sc = self._score_text_section(words, current_title, sec_body)
                    if sc > 0:
                        scored_candidates.append({
                            "score": sc,
                            "file": os.path.basename(doc_path),
                            "path": doc_path,
                            "title": current_title,
                            "raw_content": sec_body[:2400],
                        })
            except Exception:
                pass

        # 2. Scan Curated In-Memory Homelab Knowledge Base
        for kb in HOMELAB_KNOWLEDGE_BASE:
            kb_score = 0
            for kw in kb["keywords"]:
                for w in words:
                    if w == kw or (len(w) > 3 and w in kw):
                        kb_score += 9
            kb_score += self._score_text_section(words, kb["title"], kb["content"])
            if kb_score > 0:
                scored_candidates.append({
                    "score": kb_score,
                    "file": "Base Homelab Curada",
                    "path": f"kb://{kb['id']}",
                    "title": kb["title"],
                    "raw_content": kb["content"],
                })

        if not scored_candidates:
            return {"sections": [], "compressed_text": "", "sources": [], "metrics": {}}

        scored_candidates.sort(key=lambda x: x["score"], reverse=True)

        # Deduplicate by title/content prefix
        selected: List[Dict[str, Any]] = []
        seen_titles = set()
        for cand in scored_candidates:
            t_key = cand["title"].lower().strip("# ")
            if t_key in seen_titles:
                continue
            seen_titles.add(t_key)
            selected.append(cand)
            if len(selected) >= max_sections:
                break

        per_section_budget = max(400, max_chars_budget // max(len(selected), 1))
        total_raw_chars = 0
        total_comp_chars = 0
        blocks: List[str] = []
        sources: List[str] = []

        for sec in selected:
            comp_snippet, m = compress_context_for_token_budget(
                sec["raw_content"], query, max_chars=per_section_budget
            )
            sec["content"] = comp_snippet
            sec["compression_metrics"] = m
            total_raw_chars += m["raw_chars"]
            total_comp_chars += m["compressed_chars"]
            source_label = f"{sec['file']}: {sec['title']}"
            sources.append(source_label)
            blocks.append(f"• Fonte [{sec['file']} › {sec['title']}]:\n{comp_snippet}")

        compressed_text = "\n\n".join(blocks)
        saved_pct = round(
            max(0.0, (1.0 - total_comp_chars / max(total_raw_chars, 1)) * 100.0), 1
        )

        return {
            "sections": selected,
            "compressed_text": compressed_text,
            "sources": sources,
            "metrics": {
                "raw_chars": total_raw_chars,
                "compressed_chars": total_comp_chars,
                "raw_est_tokens": max(1, total_raw_chars // 4),
                "compressed_est_tokens": max(1, total_comp_chars // 4),
                "saved_pct": saved_pct,
            },
        }

    @staticmethod
    def _score_text_section(words: List[str], title: str, content: str) -> int:
        t_low = title.lower()
        c_low = content.lower()
        score = 0
        for w in words:
            if w in t_low:
                score += 10
            cnt = c_low.count(w)
            if cnt > 0:
                score += min(cnt, 4) * 2
        return score
