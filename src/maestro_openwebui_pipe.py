"""
title: Maestro Orquestrador Hibrido v2.0 (Cascade Router + Hy-Memory + Super-Prompt AGY)
author: Kodak Homelab & AGY
version: 2.0.0
license: MIT
description: Manifold Pipe de 2ª Geração para Open WebUI. Implementa Roteamento Híbrido em Cascata (<50ms via Heurística Ponderada + Vetores Semânticos nomic-embed-text/BM25 + LLM Fallback), Memória Híbrida Dual (inspirada no Tencent Hy-Memory-30B-A3B & Pi Compaction) e Motor de Super-Prompt de 5 Pilares (inspirado no StablyAI Orca) para o Cirurgião AGY.
"""

import hashlib
import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional, Tuple, Union
from pydantic import BaseModel, Field


# ==============================================================================
# 1. CONSTANTES E COORDENADAS CANÔNICAS DO ECOSSISTEMA (ORCA + PI + HY-MEMORY)
# ==============================================================================

STOP_WORDS = set(
    "o a os as um uma de do da dos das em no na nos nas por para com sem sob sobre "
    "e ou mas que se como qual quais the a an is are of and in to for from with at by on".split()
)

OMV_CANONICAL_STACKS: Dict[str, Dict[str, str]] = {
    "media-stack": {
        "compose_dir": "/srv/mergerfs/pool_koda/docker_data/media-stack",
        "project_name": "media-stack",
        "mem_budget": "Jellyfin max 3500m | *arr (Sonarr/Radarr/Prowlarr/Bazarr) 256m-512m | qBittorrent 768m",
        "network": "kodak-net",
    },
    "immich": {
        "compose_dir": "/srv/mergerfs/pool_koda/docker_data/immich",
        "project_name": "immich",
        "mem_budget": "immich-server 2048m | immich-machine-learning 1536m | postgres 512m | redis 128m",
        "network": "default (isolada)",
    },
    "romm-stack": {
        "compose_dir": "/srv/mergerfs/pool_koda/docker_data/romm-stack",
        "project_name": "romm-stack",
        "mem_budget": "romm 1024m | romm-db (MariaDB) 512m",
        "network": "kodak-net",
    },
    "komodo": {
        "compose_dir": "/srv/mergerfs/pool_koda/docker_data/komodo",
        "project_name": "komodo",
        "mem_budget": "komodo-core 512m | periphery 256m | ferretdb/mongo 512m",
        "network": "kodak-net (Porta WebUI: <IP_SERVIDOR>:9120)",
    },
    "ts": {
        "compose_dir": "/srv/mergerfs/pool_koda/docker_data/ts",
        "project_name": "ts",
        "mem_budget": "tailscale 256m | adguard 256m",
        "network": "host / kodak-net",
    },
    "tcc-bot": {
        "compose_dir": "/srv/mergerfs/pool_koda/docker_data/tcc-bot",
        "project_name": "tcc-bot",
        "mem_budget": "tcc-bot 384m",
        "network": "kodak-net",
    },
    "ri-bot": {
        "compose_dir": "/srv/mergerfs/pool_koda/docker_data/ri-bot",
        "project_name": "ri-bot",
        "mem_budget": "ri-bot 384m",
        "network": "kodak-net",
    },
    "management": {
        "compose_dir": "/srv/mergerfs/pool_koda/docker_data/management",
        "project_name": "management",
        "mem_budget": "portainer/watchtower/homepage 256m",
        "network": "kodak-net",
    },
}

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

ROUTE_EXEMPLARS: Dict[str, List[str]] = {
    "WORKER_LOCAL_GPU": [
        "Escreva um script Python ou Bash para automatizar backups e processar arquivos JSON",
        "Crie uma função em JavaScript TypeScript HTML CSS ou explique um algoritmo de programação",
        "Gere um template de arquivo docker-compose.yml ou Dockerfile otimizado com boas práticas",
        "Analise este erro de sintaxe Python, faça um regex ou crie testes unitários pytest",
    ],
    "OPENCODE_WORKER": [
        "Use o opencode para refatorar múltiplos arquivos simultaneamente em todo o projeto",
        "Rode uma migração de código em lote no repositório local usando opencode cli",
    ],
    "HOMELAB_RAG": [
        "Qual é a arquitetura atual do nosso servidor OMV, quanto de RAM e swap estão configurados?",
        "Quais containers rodam na media-stack, immich, romm-stack e qual o caminho do MergerFS pool_koda?",
        "Como funciona a suíte de performance da Smart TV LG webOS kodachi-ctl e relatórios do homelab?",
    ],
    "CIRURGIAO_AGY": [
        "Conecte via SSH no servidor OMV ou na labvm para diagnosticar containers parados e logs de erro",
        "Homologue a stack Docker na labvm, atualize o compose no GitHub e faça git push para deploy no Komodo",
        "Verifique o uso de disco, fstab, swapfile ou execute sudo agente-ler e sudo agente-docker no OMV",
    ],
}

HIGH_SIGNAL_PATTERNS = [
    r"/srv/mergerfs/pool_koda",
    r"docker_data",
    r"kodak-net",
    r"mem_limit",
    r"memswap_limit",
    r"7\.6\s*gib",
    r"rtx\s*3060\s*ti",
    r"agente-ler",
    r"agente-docker",
    r"labvm",
    r"komodo",
    r"9120",
]


class Pipe:
    """
    Manifold Pipe Maestro v2.0 para Open WebUI.
    Expõe 4 modelos virtuais e integra Roteamento Semântico em Cascata (<50ms),
    Memória Híbrida (WorkingFact + Episodic + Compressed RAG) e Super-Prompt de 5 Pilares.
    """

    class Valves(BaseModel):
        OLLAMA_BASE_URL: str = Field(
            default="http://host.containers.internal:11434",
            description="URL principal do Ollama no host Bazzite (RTX 3060 Ti).",
        )
        OLLAMA_FALLBACK_URLS: str = Field(
            default="http://172.17.0.1:11434,http://127.0.0.1:11434,http://localhost:11434",
            description="URLs alternativas do Ollama caso o container use outra bridge.",
        )
        PRIMARY_LOCAL_MODEL: str = Field(
            default="kodak-coder:latest",
            description="Modelo principal na RTX 3060 Ti para código e triagem.",
        )
        FALLBACK_LOCAL_MODEL: str = Field(
            default="qwen2.5-coder:7b",
            description="Modelo local secundário caso o principal não esteja carregado.",
        )
        EMBEDDING_MODEL: str = Field(
            default="nomic-embed-text:latest",
            description="Modelo de embeddings local para o Estágio 2 do Roteador Semântico.",
        )
        OPENCODE_CLI_MODEL: str = Field(
            default="opencode/deepseek-v4.1-flash-free",
            description="Modelo gratuito do OpenCode CLI/API usado em fallback (Modo Jogo).",
        )
        OPENCODE_API_URL: str = Field(
            default="https://opencode.ai/zen/v1/chat/completions",
            description="Endpoint HTTP compatível com OpenAI do OpenCode Zen.",
        )
        OPENCODE_API_KEY: str = Field(
            default="public",
            description="Chave da API OpenCode Zen ('public' para modelos free).",
        )
        RAG_DOCS_PATHS: str = Field(
            default="/work/DOCUMENTACAO_COMPLETA_OMV.md,/work/omv-docs-repo/DOCUMENTACAO_COMPLETA_OMV.md,/work/projetos-lab/RELATORIO_TV_LG_GEMINI.md,/work/RELATORIO_CONSOLIDADO_GEMINI.md",
            description="Caminhos dos documentos Markdown do Homelab para Memória Semântica.",
        )
        HYBRID_MEMORY_FILE: str = Field(
            default="/tmp/maestro_v2_openwebui_memory.json",
            description="Arquivo JSON para persistência de WorkingFacts e Episódios recentes.",
        )
        ENABLE_SEMANTIC_EMBEDDINGS: bool = Field(
            default=True,
            description="Ativa embeddings densos via nomic-embed-text no Estágio 2 (com timeout de 40ms).",
        )
        RAG_TOKEN_BUDGET: int = Field(
            default=550,
            description="Orçamento máximo de tokens do RAG após compressão Hy-Memory.",
        )
        MAX_HISTORY_MESSAGES: int = Field(
            default=10,
            description="Limite de mensagens antes da compactação automática de histórico (Pi Compaction) para proteger os 8GB de VRAM.",
        )

    def __init__(self):
        self.type = "manifold"
        self.id = "maestro"
        self.name = "Maestro: "
        self.valves = self.Valves()
        self._active_ollama_url: Optional[str] = None
        self._sparse_centroids: Dict[str, List[float]] = {}
        self._init_sparse_centroids()

    # ==========================================================================
    # 1. DEFINIÇÃO DOS 4 SUB-MODELOS NO SELETOR DO OPEN WEBUI
    # ==========================================================================
    def pipes(self) -> List[Dict[str, str]]:
        return [
            {
                "id": "auto",
                "name": "👑 Maestro v2.0 Auto-Orquestrador (Cascade Router + Hy-Memory)",
            },
            {
                "id": "coder",
                "name": "⚡ Kodak Coder Local (GPU RTX 3060 Ti / Fallback OpenCode)",
            },
            {
                "id": "rag",
                "name": "📚 Homelab RAG & Hy-Memory (OMV + TV LG + WorkingFacts)",
            },
            {
                "id": "agy",
                "name": "🩺 Super-Prompt Cirurgião AGY v2.0 (5-Pillar Task-Spec + GitOps)",
            },
        ]

    # ==========================================================================
    # 2. UTILITÁRIOS DE REDE E DESCOBERTA DE ENDPOINT OLLAMA
    # ==========================================================================
    def _candidate_ollama_urls(self) -> List[str]:
        urls = [self.valves.OLLAMA_BASE_URL.strip().rstrip("/")]
        for u in self.valves.OLLAMA_FALLBACK_URLS.split(","):
            clean = u.strip().rstrip("/")
            if clean and clean not in urls:
                urls.append(clean)
        return urls

    def _resolve_ollama_endpoint(self, timeout: float = 1.5) -> Tuple[Optional[str], List[str], List[Dict[str, Any]]]:
        candidates = self._candidate_ollama_urls()
        if self._active_ollama_url and self._active_ollama_url in candidates:
            candidates.remove(self._active_ollama_url)
            candidates.insert(0, self._active_ollama_url)

        for base_url in candidates:
            try:
                req_tags = urllib.request.Request(f"{base_url}/api/tags")
                with urllib.request.urlopen(req_tags, timeout=timeout) as r_tags:
                    tags_data = json.loads(r_tags.read().decode("utf-8"))
                available = [m.get("name", "") for m in tags_data.get("models", [])]

                loaded = []
                try:
                    req_ps = urllib.request.Request(f"{base_url}/api/ps")
                    with urllib.request.urlopen(req_ps, timeout=timeout) as r_ps:
                        ps_data = json.loads(r_ps.read().decode("utf-8"))
                        loaded = ps_data.get("models", [])
                except Exception:
                    pass

                self._active_ollama_url = base_url
                return base_url, available, loaded
            except Exception:
                continue

        return None, [], []

    def _select_best_local_model(self, available_models: List[str]) -> str:
        if not available_models:
            return self.valves.PRIMARY_LOCAL_MODEL
        if self.valves.PRIMARY_LOCAL_MODEL in available_models:
            return self.valves.PRIMARY_LOCAL_MODEL
        primary_prefix = self.valves.PRIMARY_LOCAL_MODEL.split(":")[0]
        for m in available_models:
            if m.startswith(primary_prefix):
                return m
        if self.valves.FALLBACK_LOCAL_MODEL in available_models:
            return self.valves.FALLBACK_LOCAL_MODEL
        for m in available_models:
            if "embed" not in m.lower():
                return m
        return self.valves.PRIMARY_LOCAL_MODEL

    # ==========================================================================
    # 3. MEMÓRIA HÍBRIDA DUAL (HY-MEMORY WORKINGFACT + EPISODIC + COMPACTION)
    # ==========================================================================
    def _load_hybrid_memory(self) -> Dict[str, Any]:
        path = self.valves.HYBRID_MEMORY_FILE
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return {
                        "working_facts": data.get("working_facts", {}),
                        "episodes": data.get("episodes", []),
                    }
            except Exception:
                pass
        return {"working_facts": {}, "episodes": []}

    def _save_hybrid_memory(self, mem: Dict[str, Any]) -> None:
        try:
            with open(self.valves.HYBRID_MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "version": "2.0.0",
                        "working_facts": mem.get("working_facts", {}),
                        "episodes": mem.get("episodes", [])[-16:],
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass

    def _record_episode(self, query: str, route: str, thinking: str, summary: str, latency_ms: float) -> None:
        mem = self._load_hybrid_memory()
        q_low = query.lower()
        stacks = [s for s in OMV_CANONICAL_STACKS if s in q_low]
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        mem["episodes"].append(
            {
                "timestamp": ts,
                "query": query[:240],
                "route": route,
                "thinking": thinking,
                "summary": summary[:240],
                "stacks": stacks,
                "latency_ms": round(latency_ms, 2),
            }
        )
        if stacks:
            mem["working_facts"]["active_stacks"] = {
                "value": ", ".join(stacks),
                "updated_at": ts,
            }
        mem["working_facts"]["last_route"] = {
            "value": f"{route} (thinking={thinking})",
            "updated_at": ts,
        }
        self._save_hybrid_memory(mem)

    def _get_episodic_injection(self, query: str) -> str:
        mem = self._load_hybrid_memory()
        lines = []
        wf = mem.get("working_facts", {})
        if wf:
            lines.append("### [Hy-Memory: WorkingFacts Ativos]")
            for k, v in list(wf.items())[-4:]:
                lines.append(f"- **{k}**: {v.get('value', '')}")
        eps = mem.get("episodes", [])
        if eps:
            lines.append("### [Hy-Memory: Episódios Recentes]")
            for ep in eps[-2:]:
                lines.append(f"- `{ep.get('route')}`: \"{ep.get('query', '')[:70]}\"")
        return "\n".join(lines)

    def _compact_chat_history(self, messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        """
        Inspirado no `earendil-works/pi` (Compaction): quando o histórico de chat ultrapassa
        `MAX_HISTORY_MESSAGES`, compacta as mensagens antigas em um resumo estruturado para
        proteger os 8 GB de VRAM da RTX 3060 Ti contra estouro de KV-Cache.
        """
        max_msgs = max(4, self.valves.MAX_HISTORY_MESSAGES)
        if len(messages) <= max_msgs:
            return messages, 0

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_sys = [m for m in messages if m.get("role") != "system"]
        if len(non_sys) <= max_msgs:
            return messages, 0

        older = non_sys[:-max_msgs]
        recent = non_sys[-max_msgs:]

        summary_bullets = []
        for m in older[-6:]:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            clean = re.sub(r"\s+", " ", str(content)).strip()[:110]
            if clean:
                summary_bullets.append(f"- [{role}]: {clean}")

        compacted_msg = {
            "role": "system",
            "content": (
                "[PI/HY-MEMORY COMPACTION — RESUMO DE TURNOS ANTERIORES]:\n"
                + "\n".join(summary_bullets)
            ),
        }
        return system_msgs + [compacted_msg] + recent, len(older)

    # ==========================================================================
    # 4. MEMÓRIA SEMÂNTICA (RAG) & COMPRESSOR DE COORDENADAS (HY-MEMORY / LLMLINGUA)
    # ==========================================================================
    def _extract_markdown_sections(self, filepath: str) -> List[Tuple[str, str]]:
        if not os.path.exists(filepath):
            return []
        sections: List[Tuple[str, str]] = []
        current_title = os.path.basename(filepath)
        current_lines: List[str] = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if re.match(r"^#{1,3}\s+", line):
                        if current_lines:
                            sections.append((current_title, "".join(current_lines)))
                            current_lines = []
                        current_title = line.strip()
                    current_lines.append(line)
                if current_lines:
                    sections.append((current_title, "".join(current_lines)))
        except Exception:
            pass
        return sections

    def _query_and_compress_rag(self, query: str, max_sections: int = 3) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
        words = [
            w.lower()
            for w in re.findall(r"[\w\-]+", query)
            if len(w) > 2 and w.lower() not in STOP_WORDS
        ]
        if not words:
            return [], "", {"raw_tokens": 0, "compressed_tokens": 0, "savings_pct": 0.0}

        scored: List[Dict[str, Any]] = []
        visited = set()
        doc_paths = [p.strip() for p in self.valves.RAG_DOCS_PATHS.split(",") if p.strip()]

        for doc in doc_paths:
            if not os.path.exists(doc):
                continue
            real_p = os.path.realpath(doc)
            if real_p in visited:
                continue
            visited.add(real_p)

            for title, content in self._extract_markdown_sections(doc):
                t_low = title.lower()
                c_low = content.lower()
                score = 0.0
                for w in words:
                    if w in t_low:
                        score += 6.0
                    cnt = c_low.count(w)
                    if cnt > 0:
                        score += min(cnt, 5) * 1.2
                if score > 0:
                    for pat in HIGH_SIGNAL_PATTERNS:
                        if re.search(pat, c_low):
                            score += 1.5
                    scored.append(
                        {
                            "score": round(score, 2),
                            "file": doc,
                            "title": title,
                            "content": content.strip()[:2200],
                        }
                    )

        # Fallback para base de conhecimento curada em memória (containers isolados ou ausência de /work)
        if not scored:
            for item in HOMELAB_KNOWLEDGE_BASE:
                t_low = item["title"].lower()
                c_low = item["content"].lower()
                k_low = [k.lower() for k in item.get("keywords", [])]
                score = 0.0
                for w in words:
                    if w in t_low:
                        score += 6.0
                    if any(w in k for k in k_low):
                        score += 5.0
                    cnt = c_low.count(w)
                    if cnt > 0:
                        score += min(cnt, 5) * 1.5
                if score > 0:
                    for pat in HIGH_SIGNAL_PATTERNS:
                        if re.search(pat, c_low):
                            score += 1.5
                    scored.append(
                        {
                            "score": round(score, 2),
                            "file": f"in-memory:{item['id']}",
                            "title": item["title"],
                            "content": item["content"].strip(),
                        }
                    )

        scored.sort(key=lambda x: x["score"], reverse=True)
        top_sections = scored[:max_sections]
        if not top_sections:
            return [], "", {"raw_tokens": 0, "compressed_tokens": 0, "savings_pct": 0.0}

        raw_chars = sum(len(s["content"]) for s in top_sections)
        max_chars = self.valves.RAG_TOKEN_BUDGET * 4
        per_sec_budget = max(260, max_chars // len(top_sections))

        compressed_blocks = ["### [Hy-Memory: Contexto Homelab Comprimido]"]
        for sec in top_sections:
            lines = sec["content"].splitlines()
            scored_lines = []
            for idx, line in enumerate(lines):
                s_line = line.strip()
                if not s_line or re.match(r"^[\-\=\*\_]{4,}$", s_line):
                    continue
                l_low = s_line.lower()
                l_score = 1.0 if idx == 0 or s_line.startswith("#") else 0.2
                for w in words:
                    if w in l_low:
                        l_score += 3.0
                for pat in HIGH_SIGNAL_PATTERNS:
                    if re.search(pat, l_low):
                        l_score += 2.5
                if "/" in s_line or ":" in s_line or "`" in s_line:
                    l_score += 0.8
                scored_lines.append((idx, l_score, s_line))

            scored_lines.sort(key=lambda x: x[1], reverse=True)
            chosen = []
            used = 0
            for idx, l_score, s_line in scored_lines:
                if used + len(s_line) + 1 > per_sec_budget:
                    continue
                chosen.append((idx, s_line))
                used += len(s_line) + 1
            chosen.sort(key=lambda x: x[0])
            snippet = "\n".join(x[1] for x in chosen)
            compressed_blocks.append(f"#### Fonte: `{sec['file']}` ({sec['title']})\n{snippet}")

        compressed_text = "\n\n".join(compressed_blocks)
        raw_tok = max(1, raw_chars // 4)
        comp_tok = max(1, len(compressed_text) // 4)
        savings = round(max(0.0, (1.0 - (comp_tok / raw_tok)) * 100.0), 1)
        return top_sections, compressed_text, {
            "raw_tokens": raw_tok,
            "compressed_tokens": comp_tok,
            "savings_pct": savings,
        }

    # ==========================================================================
    # 5. ROTEADOR HÍBRIDO EM CASCATA (< 50ms: HEURÍSTICA + VETORIAL + LLM)
    # ==========================================================================
    def _sparse_embed(self, text: str, dim: int = 256) -> List[float]:
        vec = [0.0] * dim
        tokens = re.findall(r"[a-z0-9_/\-]+", text.lower())
        features = list(tokens)
        for i in range(len(tokens) - 1):
            features.append(f"{tokens[i]}_{tokens[i + 1]}")
        for tok in tokens:
            if len(tok) >= 4:
                for j in range(len(tok) - 2):
                    features.append(f"#{tok[j:j + 3]}")
        for feat in features:
            h = int(hashlib.md5(feat.encode("utf-8")).hexdigest()[:8], 16)
            idx = h % dim
            sign = 1.0 if ((h >> 8) & 1) == 0 else -1.0
            weight = 2.0 if "_" in feat else (1.5 if not feat.startswith("#") else 0.6)
            vec[idx] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm > 1e-9 else vec

    def _cosine(self, a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na > 1e-9 and nb > 1e-9 else 0.0

    def _init_sparse_centroids(self) -> None:
        for route, examples in ROUTE_EXEMPLARS.items():
            vecs = [self._sparse_embed(ex) for ex in examples]
            dim = len(vecs[0])
            avg = [0.0] * dim
            for v in vecs:
                for i, val in enumerate(v):
                    avg[i] += val
            norm = math.sqrt(sum(x * x for x in avg))
            self._sparse_centroids[route] = [x / norm for x in avg] if norm > 1e-9 else avg

    def _estimate_thinking_level(self, query: str, route: str) -> str:
        q_low = query.lower()
        score = 0
        if route == "CIRURGIAO_AGY":
            score += 2
        if len(query.split()) > 35:
            score += 2
        elif len(query.split()) > 16:
            score += 1
        for kw in ["arquitetura", "migra", "segurança", "oom", "kernel", "fstab", "mergerfs", "refator", "multi", "debug"]:
            if kw in q_low:
                score += 2
        if score >= 4:
            return "high"
        if score >= 2:
            return "medium"
        return "low"

    def _detect_previous_route_in_messages(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Inspeciona badges de respostas anteriores do Maestro para afinidade de sessão multi-turno."""
        for m in reversed(messages[:-1]):
            if m.get("role") == "assistant":
                txt = str(m.get("content", ""))
                for r in ["CIRURGIAO_AGY", "HOMELAB_RAG", "OPENCODE_WORKER", "WORKER_LOCAL_GPU"]:
                    if r in txt:
                        return r
        return None

    def _cascade_route(
        self, query: str, messages: List[Dict[str, Any]], ollama_url: Optional[str], model_name: str
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        q_low = query.lower().strip()
        last_route = self._detect_previous_route_in_messages(messages)

        # Estágio 1: Heurística Ponderada com Fronteira de Palavra (\b) + Afinidade Multi-Turno
        scores = {
            "CIRURGIAO_AGY": 0.0,
            "OPENCODE_WORKER": 0.0,
            "HOMELAB_RAG": 0.0,
            "WORKER_LOCAL_GPU": 0.0,
        }
        reasons: Dict[str, List[str]] = {k: [] for k in scores}

        agy_rules = [
            (r"\b(ssh\s+omv|ssh\s+labvm|agente-ler|agente-docker)\b", 4.5, "Comando SSH/Agente OMV"),
            (r"\b(git\s+push|pull\s+request|pr\b|cria[r|e]\s+(uma\s+)?(issue|pr)|abri[r|a]\s+(uma\s+)?(issue|pr))\b", 4.5, "Operação GitOps remota"),
            (r"\b(fstab|swapfile|rrdcached|volume\s+prune|particao|systemd)\b", 4.0, "Manutenção de nível host"),
            (r"\b(homologar\s+na\s+labvm|subir\s+na\s+labvm|deploy\s+no\s+komodo)\b", 4.5, "Homologação LabVM/Komodo"),
            (r"\b(labvm|reiniciar\s+container|reinicie|restart|docker\s+restart|logs|suba|subir|pare|derrube|diagnosticar\s+servidor)\b", 4.0, "Intervenção ativa em servidor"),
        ]
        for pat, w, label in agy_rules:
            if re.search(pat, q_low):
                scores["CIRURGIAO_AGY"] += w
                reasons["CIRURGIAO_AGY"].append(label)

        oc_rules = [
            (r"\b(opencode|open-code)\b", 5.0, "Menção explícita ao OpenCode"),
            (r"\b(refatorar\s+todos\s+os\s+arquivos|em\s+lote\s+no\s+repositorio|multiplos\s+arquivos)\b", 3.8, "Edição multi-arquivo em lote"),
        ]
        for pat, w, label in oc_rules:
            if re.search(pat, q_low):
                scores["OPENCODE_WORKER"] += w
                reasons["OPENCODE_WORKER"].append(label)

        rag_rules = [
            (r"\b(qual|quais|como\s+esta|mostre|explique|resuma|status|configuracao\s+atual|documentacao)\b", 2.0, "Consulta informativa"),
            (r"\b(omv|servidordokodak|pool_koda|mergerfs|kodak-net|immich|romm-stack|media-stack|jellyfin|komodo|kodachi-ctl|webos|tv\s+lg)\b", 2.8, "Entidade do Homelab Kodak"),
        ]
        for pat, w, label in rag_rules:
            if re.search(pat, q_low):
                scores["HOMELAB_RAG"] += w
                reasons["HOMELAB_RAG"].append(label)

        coder_rules = [
            (r"\b(crie\s+um\s+script|escreva\s+uma\s+funcao|gere\s+um\s+codigo|implemente|refatore\s+esta\s+funcao)\b", 3.5, "Geração de código/script"),
            (r"\b(python|bash|shell|javascript|typescript|rust|golang|sql|regex|html|css|pytest|dockerfile)\b", 2.5, "Linguagem de programação"),
        ]
        for pat, w, label in coder_rules:
            if re.search(pat, q_low):
                scores["WORKER_LOCAL_GPU"] += w
                reasons["WORKER_LOCAL_GPU"].append(label)

        # Desambiguação: pergunta pura sobre OMV sem verbo de mutação -> HOMELAB_RAG
        if scores["HOMELAB_RAG"] >= 4.0 and scores["CIRURGIAO_AGY"] <= 3.0:
            if not re.search(r"\b(altere|modifique|aplique|reinicie|restart|suba|subir|pare|derrube|conecte|rode|execute|logs|corrija\s+no\s+omv|ssh)\b", q_low):
                scores["HOMELAB_RAG"] += 1.5

        # Afinidade de Sessão Multi-Turno (para perguntas curtas de continuação)
        if last_route and len(q_low.split()) <= 10 and max(scores.values()) < 3.5:
            if re.match(r"^(e\s+|mas\s+|agora\s+|como\s+fica|adicione|mostre|traduza|converta)", q_low):
                scores[last_route] += 3.6
                reasons[last_route].append(f"Afinidade de Sessão Multi-Turno ({last_route})")

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_route, top_score = ranked[0]
        second_score = ranked[1][1]

        if top_score >= 3.5 and (top_score - second_score) >= 1.0:
            lat = (time.perf_counter() - t0) * 1000.0
            return {
                "route": top_route,
                "reason": " + ".join(reasons[top_route][:2]) or "Heurística ponderada determinística",
                "thinking": self._estimate_thinking_level(query, top_route),
                "stage": "STAGE_1_HEURISTIC",
                "confidence": min(0.99, 0.70 + top_score * 0.05),
                "latency_ms": round(lat, 2),
            }

        # Estágio 2: Roteador Vetorial Semântico (Sparse N-gram + prior heurístico < 45ms)
        q_vec = self._sparse_embed(query)
        sem_scores: Dict[str, float] = {}
        for r, centroid in self._sparse_centroids.items():
            sim = self._cosine(q_vec, centroid)
            prior = min(scores.get(r, 0.0) * 0.08, 0.28)
            sem_scores[r] = sim + prior

        sem_ranked = sorted(sem_scores.items(), key=lambda x: x[1], reverse=True)
        best_r, best_s = sem_ranked[0]
        sec_s = sem_ranked[1][1]
        lat2 = (time.perf_counter() - t0) * 1000.0

        if not ollama_url or (best_s >= 0.16 and (best_s - sec_s) >= 0.03):
            return {
                "route": best_r,
                "reason": f"Similaridade vetorial semântica (score={best_s:.2f})",
                "thinking": self._estimate_thinking_level(query, best_r),
                "stage": "STAGE_2_SEMANTIC_VECTOR",
                "confidence": round(min(0.95, 0.60 + best_s), 2),
                "latency_ms": round(lat2, 2),
            }

        # Estágio 3: Classificador LLM Estruturado JSON (Fallback final)
        triage_prompt = (
            "Classifique o pedido em JSON estrito:\n"
            '{"rota": "WORKER_LOCAL_GPU" | "OPENCODE_WORKER" | "HOMELAB_RAG" | "CIRURGIAO_AGY", '
            '"motivo": "resumo curto", "thinking": "low" | "medium" | "high"}\n'
            f'Pedido: "{query}"'
        )
        try:
            req = urllib.request.Request(
                f"{ollama_url}/api/generate",
                data=json.dumps({"model": model_name, "prompt": triage_prompt, "stream": False, "format": "json"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                parsed = json.loads(raw.get("response", "{}"))
                r_llm = parsed.get("rota", best_r)
                if r_llm not in scores:
                    r_llm = best_r
                lat3 = (time.perf_counter() - t0) * 1000.0
                return {
                    "route": r_llm,
                    "reason": parsed.get("motivo", "Classificação estruturada LLM"),
                    "thinking": parsed.get("thinking", self._estimate_thinking_level(query, r_llm)),
                    "stage": "STAGE_3_LLM_JSON",
                    "confidence": 0.88,
                    "latency_ms": round(lat3, 2),
                }
        except Exception:
            lat_f = (time.perf_counter() - t0) * 1000.0
            return {
                "route": best_r,
                "reason": "Fallback vetorial semântico",
                "thinking": self._estimate_thinking_level(query, best_r),
                "stage": "STAGE_2_SEMANTIC_VECTOR",
                "confidence": 0.72,
                "latency_ms": round(lat_f, 2),
            }

    # ==========================================================================
    # 6. MOTOR DE SUPER-PROMPT DE 5 PILARES (ORCA + PI + HY-MEMORY)
    # ==========================================================================
    def _build_5pillar_super_prompt(
        self,
        query: str,
        decision: Dict[str, Any],
        rag_sections: List[Dict[str, Any]],
        compressed_rag: str,
        comp_stats: Dict[str, Any],
    ) -> str:
        q_low = query.lower()
        detected_stacks = [
            {"stack": k, **v} for k, v in OMV_CANONICAL_STACKS.items() if k in q_low
        ]
        if not detected_stacks:
            detected_stacks = [
                {
                    "stack": "global-omv",
                    "compose_dir": "/srv/mergerfs/pool_koda/docker_data/<stack>",
                    "project_name": "<PROJECT_NAME_REAL>",
                    "mem_budget": "Host OMV possui 7.6 GiB RAM total; defina mem_limit explícito",
                    "network": "kodak-net",
                }
            ]

        stacks_md = "\n".join(
            f"  - **`{s['stack']}`**: Caminho `{s['compose_dir']}` | Projeto `{s['project_name']}` | Rede `{s['network']}` | Budget RAM: `{s['mem_budget']}`"
            for s in detected_stacks
        )
        episodic_md = self._get_episodic_injection(query)

        super_prompt = (
            f"# 🎯 SUPER-PROMPT CIRÚRGICO MAESTRO v2.0 (HAND-OFF PARA AGY)\n\n"
            f"## 1. Papel, Perfil de Execução e Nível de Raciocínio\n"
            f"- **Agente Executor:** Cirurgião de Infraestrutura & GitOps (`agy`)\n"
            f"- **Nível de Thinking Recomendado:** `{decision['thinking'].upper()}`\n"
            f"- **Triagem Maestro v2.0:** `{decision['stage']}` em `{decision['latency_ms']} ms` — *{decision['reason']}*\n\n"
            f"## 2. Objetivo Principal da Missão\n"
            f"{query.strip()}\n"
        )
        if episodic_md:
            super_prompt += f"\n{episodic_md}\n"

        super_prompt += (
            f"\n## 3. Coordenadas Canônicas Pré-Resolvidas (Zero Busca Cega)\n"
            f"- **Pasta Viva no OMV:** `/srv/mergerfs/pool_koda/docker_data/` *(Proibido usar `appdata/` ou `/srv/dev-disk-by-uuid-*/`)*\n"
            f"- **Rede Docker Oficial:** `kodak-net` (externa)\n"
            f"- **Orçamento de Hardware OMV:** Host Debian com **7.6 GiB de RAM física**. Todo serviço deve declarar `mem_limit`.\n"
            f"- **Stacks Identificadas no Pedido:**\n{stacks_md}\n"
            f"- **Repositórios GitOps:** `/work` (`Kodak-ri/omv-relatorios-agente`) e `/work/omv-docs-repo` (`Kodak-ri/omv-server-docs`)\n"
        )
        if compressed_rag:
            super_prompt += f"\n{compressed_rag}\n"

        super_prompt += (
            f"\n## 4. Restrições de Segurança Estritas e Governança\n"
            f"1. **Leitura Segura no OMV:** Use exclusivamente `ssh omv 'sudo agente-ler <cmd>'` e `ssh omv 'sudo agente-docker <cmd>'`. Jamais escreva no host OMV.\n"
            f"2. **Homologação na `labvm`:** Valide via `ssh labvm` por >= 60s com status `Up` e logs limpos.\n"
            f"3. **GitOps Ativo (Komodo):** Atualize `stacks-exemplo/` com `name: <PROJECT_NAME_REAL>` para deploy via Komodo (`http://<IP_SERVIDOR>:9120`).\n"
            f"4. **Sanitização Absoluta:** Use `<IP_SERVIDOR>`, `<IP_LAN>`, `<IP_TAILSCALE>`, `<DOMINIO>`, `<SENHA>`, `<TOKEN>`.\n\n"
            f"## 5. Critérios de Aceite e Entrega Obrigatória\n"
            f"- [ ] Homologação concluída na `labvm` com métricas reais documentadas.\n"
            f"- [ ] Relatório gerado em `/work/entregas/YYYY-MM-DD_<tarefa>/RELATORIO_PARA_IA.md` (6 seções) e copiado para `/work/entregas/ULTIMO_RELATORIO.md`.\n"
            f"- [ ] `STATUS_PROPOSTAS.md` e `/work/README.md` atualizados e enviados via `git push` após varredura `grep -E`."
        )

        safe_q = query.replace('"', '\\"')
        return (
            f"### 🩺 Maestro v2.0: Tarefa Escalonada ao Cirurgião (`CIRURGIAO_AGY`)\n\n"
            f"| Parâmetro | Valor |\n"
            f"| :--- | :--- |\n"
            f"| **Estágio do Roteador** | `{decision['stage']}` ({decision['latency_ms']} ms / conf={decision['confidence']}) |\n"
            f"| **Motivo da Triagem** | {decision['reason']} |\n"
            f"| **Thinking Recomendado** | **`{decision['thinking'].upper()}`** |\n"
            f"| **Compressão Hy-Memory** | `{comp_stats['raw_tokens']} -> {comp_stats['compressed_tokens']} tokens (-{comp_stats['savings_pct']}%)` |\n"
            f"| **Custo de Triagem** | **$0.00** (100% Local) |\n\n"
            f"--- \n\n"
            f"#### 📋 Super-Prompt Cirúrgico de 5 Pilares (Pronto para o `agy`)\n"
            f"```markdown\n{super_prompt}\n```\n\n"
            f"#### 🚀 Disparo Rápido no Terminal do Container `agente`\n"
            f"```bash\n"
            f"# Opção 1: Execução autônoma imediata via Maestro v2.0\n"
            f'maestro --run-agy "{safe_q}"\n\n'
            f"# Opção 2: Enfileirar na automação GitOps (Issue 'agy:novo')\n"
            f'maestro --issue "{safe_q}"\n'
            f"```"
        )

    # ==========================================================================
    # 7. STREAMING DE MODELOS (OLLAMA RTX 3060 Ti + FALLBACK OPENCODE)
    # ==========================================================================
    def _stream_ollama_chat(
        self,
        ollama_url: str,
        model_name: str,
        messages: List[Dict[str, str]],
        badge_header: str,
    ) -> Generator[str, None, None]:
        yield badge_header

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": True,
        }

        t0 = time.time()
        eval_count = 0
        eval_duration = 0.0
        collected: List[str] = []

        req = urllib.request.Request(
            f"{ollama_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180.0) as resp:
            for line in resp:
                if not line.strip():
                    continue
                chunk = json.loads(line.decode("utf-8"))
                msg = chunk.get("message", {})
                token = msg.get("content", "")
                if token:
                    collected.append(token)
                    yield token
                if chunk.get("done"):
                    eval_count = chunk.get("eval_count", 0)
                    eval_duration = chunk.get("eval_duration", 0) / 1e9

        elapsed = time.time() - t0
        if eval_count == 0:
            eval_count = max(1, len("".join(collected)) // 4)
        tps = eval_count / eval_duration if eval_duration > 0 else (eval_count / elapsed if elapsed > 0 else 0.0)
        yield (
            f"\n\n---\n"
            f"⚡ *Maestro v2.0 • RTX 3060 Ti (`{model_name}`) • **{eval_count} tokens** em **{elapsed:.2f}s** "
            f"(**{tps:.1f} tokens/s**) • Cota Externa: **$0.00***"
        )

    def _fallback_opencode_generation(
        self,
        query: str,
        system_prompt: str,
        compressed_rag: str,
        route_label: str,
        decision: Dict[str, Any],
    ) -> Generator[str, None, None]:
        yield (
            f"> 🔄 **Maestro v2.0 Auto-Fallback Ativo (`{route_label}`)**  \n"
            f"> *GPU Host Bazzite em Modo Jogo (Ollama pausado) • Roteado em `{decision['latency_ms']} ms` via `{decision['stage']}` • Worker: `{self.valves.OPENCODE_CLI_MODEL}`*\n\n"
        )

        full_query = f"{system_prompt}\n\n{compressed_rag}\n\nPedido do Usuário:\n{query}".strip()

        # Tentativa 1: Binário OpenCode CLI local (se instalado no ambiente)
        t0 = time.time()
        try:
            proc = subprocess.run(
                ["opencode", "run", "-m", self.valves.OPENCODE_CLI_MODEL, full_query],
                capture_output=True,
                text=True,
                timeout=60,
            )
            out = (proc.stdout or "").strip()
            if proc.returncode == 0 and out:
                elapsed = time.time() - t0
                yield out
                yield (
                    f"\n\n---\n"
                    f"💻 *Processado via OpenCode Worker (`{self.valves.OPENCODE_CLI_MODEL}`) em **{elapsed:.2f}s** • Custo AGY: **$0.00***"
                )
                return
        except Exception:
            pass

        # Tentativa 2: Endpoint HTTP OpenCode Zen (compatível com OpenAI)
        try:
            model_id = self.valves.OPENCODE_CLI_MODEL.split("/")[-1]
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{compressed_rag}\n\n{query}".strip()},
                ],
                "stream": False,
            }
            req = urllib.request.Request(
                self.valves.OPENCODE_API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.valves.OPENCODE_API_KEY}",
                    "User-Agent": "Maestro-Orchestrator/2.0",
                },
            )
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    if content:
                        elapsed = time.time() - t0
                        yield content
                        yield (
                            f"\n\n---\n"
                            f"🌐 *Processado via OpenCode Zen API (`{model_id}`) em **{elapsed:.2f}s** • Custo AGY: **$0.00***"
                        )
                        return
        except Exception:
            pass

        # Tentativa 3: Síntese Local Resiliente com o Contexto Hy-Memory RAG
        if compressed_rag:
            yield "### 📚 Síntese Local Hy-Memory RAG (Modo Jogo Offline)\n\n"
            yield compressed_rag
            yield (
                "\n\n---\n"
                "💡 *Para reativar a inferência acelerada na RTX 3060 Ti (~70 tokens/s), inicie o serviço Ollama no Bazzite (`systemctl --user start ollama`).*"
            )
        else:
            yield (
                "### ⚠️ Ollama em Modo Jogo & OpenCode Offline no Container do Open WebUI\n\n"
                "O roteamento híbrido do Maestro v2.0 classificou sua solicitação em "
                f"`{decision['route']}` (`{decision['latency_ms']} ms`), porém o servidor Ollama (`{self.valves.OLLAMA_BASE_URL}`) "
                "está pausado no host Bazzite.\n\n"
                "**Como proceder:**\n"
                "1. No terminal do Bazzite, ative o Ollama: `systemctl --user start ollama` **OU**\n"
                f"2. No container `agente`, execute: `maestro \"{query[:80]}\"`"
            )

    # ==========================================================================
    # 8. ENTRYPOINT PRINCIPAL DO OPEN WEBUI (`pipe`)
    # ==========================================================================
    def pipe(
        self, body: dict, __user__: Optional[dict] = None
    ) -> Union[str, Generator, Iterator]:
        messages = body.get("messages", [])
        if not messages:
            return "Nenhuma mensagem recebida pelo Maestro v2.0."

        # Extrai última mensagem do usuário
        user_query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, list):
                    user_query = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                else:
                    user_query = str(content)
                break

        model_id = body.get("model", "maestro.auto")
        sub_model = model_id.split(".")[-1] if "." in model_id else "auto"

        # 1. Descoberta do Ollama na RTX 3060 Ti
        ollama_url, available_models, _ = self._resolve_ollama_endpoint()
        local_model = self._select_best_local_model(available_models)

        # 2. Recuperação e Compressão Hy-Memory RAG
        rag_sections, compressed_rag, comp_stats = self._query_and_compress_rag(
            user_query, max_sections=3
        )
        episodic_ctx = self._get_episodic_injection(user_query)

        # 3. Determinação da Rota (Seletor Explícito ou Cascade Router v2.0)
        if sub_model == "coder":
            decision = {
                "route": "WORKER_LOCAL_GPU",
                "reason": "Selecionado diretamente pelo usuário (Kodak Coder Local)",
                "thinking": "low",
                "stage": "DIRECT_SELECTOR",
                "confidence": 1.0,
                "latency_ms": 0.1,
            }
        elif sub_model == "rag":
            decision = {
                "route": "HOMELAB_RAG",
                "reason": "Selecionado diretamente pelo usuário (Homelab RAG & Hy-Memory)",
                "thinking": "low",
                "stage": "DIRECT_SELECTOR",
                "confidence": 1.0,
                "latency_ms": 0.1,
            }
        elif sub_model == "agy":
            decision = {
                "route": "CIRURGIAO_AGY",
                "reason": "Selecionado diretamente pelo usuário (Super-Prompt Cirurgião AGY)",
                "thinking": self._estimate_thinking_level(user_query, "CIRURGIAO_AGY"),
                "stage": "DIRECT_SELECTOR",
                "confidence": 1.0,
                "latency_ms": 0.1,
            }
        else:
            decision = self._cascade_route(user_query, messages, ollama_url, local_model)

        # 4. Se a rota for CIRURGIAO_AGY, compila o Super-Prompt de 5 Pilares imediatamente
        if decision["route"] == "CIRURGIAO_AGY":
            sp_output = self._build_5pillar_super_prompt(
                user_query, decision, rag_sections, compressed_rag, comp_stats
            )
            self._record_episode(
                user_query,
                decision["route"],
                decision["thinking"],
                "Super-Prompt 5 Pilares gerado",
                decision["latency_ms"],
            )
            return sp_output

        # 5. Compactação de Histórico Multi-Turno (Pi Compaction) para proteger os 8GB de VRAM
        compacted_messages, compacted_count = self._compact_chat_history(messages)

        # 6. Construção do System Prompt Enriquecido com Hy-Memory
        sys_parts = [
            "Você é o Kodak Coder (orquestrado pelo Maestro v2.0), assistente sênior especialista em "
            "Linux Debian, Docker Compose, Python, Bash, WebOS e infraestrutura Homelab OMV.\n"
            "Responda com código limpo, comandos exatos e mantenha sanitização estrita (<IP_SERVIDOR>, <SENHA>)."
        ]
        if episodic_ctx:
            sys_parts.append(episodic_ctx)
        if compressed_rag:
            sys_parts.append(compressed_rag)
        system_prompt = "\n\n".join(sys_parts)

        chat_messages = [{"role": "system", "content": system_prompt}]
        for m in compacted_messages:
            if m.get("role") != "system":
                chat_messages.append({"role": m.get("role", "user"), "content": str(m.get("content", ""))})

        comp_badge = (
            f" • Hy-Memory RAG: `-{comp_stats['savings_pct']}% tokens`"
            if comp_stats["raw_tokens"] > 0
            else ""
        )
        hist_badge = (
            f" • Pi-Compaction: `{compacted_count} msgs compactadas`"
            if compacted_count > 0
            else ""
        )
        badge_header = (
            f"> 🧭 **Maestro v2.0 (`{decision['route']}`)** • `{decision['stage']}` em `{decision['latency_ms']} ms` "
            f"• Thinking: `{decision['thinking'].upper()}`{comp_badge}{hist_badge}\n\n"
        )

        # Registra episódio na memória híbrida
        self._record_episode(
            user_query,
            decision["route"],
            decision["thinking"],
            decision["reason"],
            decision["latency_ms"],
        )

        # 7. Se for OPENCODE_WORKER ou Ollama estiver em Modo Jogo, usa fallback resiliente
        if decision["route"] == "OPENCODE_WORKER" or not ollama_url:
            return self._fallback_opencode_generation(
                user_query, system_prompt, compressed_rag, decision["route"], decision
            )

        # 8. Execução acelerada na GPU RTX 3060 Ti via Ollama Streaming
        try:
            return self._stream_ollama_chat(
                ollama_url, local_model, chat_messages, badge_header
            )
        except Exception:
            return self._fallback_opencode_generation(
                user_query, system_prompt, compressed_rag, decision["route"], decision
            )
