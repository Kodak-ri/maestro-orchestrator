#!/usr/bin/env python3
"""
Maestro v2.0 — Structured Meta-Prompter & Canonical Coordinate Resolver (Super-Prompt Engine).

Inspired by:
1. StablyAI Orca (`orchestration.md` Task-Spec Contract):
   - Every delegated task specification is self-contained and enforces 5 mandatory pillars:
     Target, Change, Constraints, Ownership, and Observable Acceptance.
2. Earendil Works Pi (`handoff.ts` & `prompt-templates.md`):
   - Focused context transfer extracting prior decisions, canonical files, and a self-contained
     next task without dumping raw chat history.
3. Stanford DSPy Signatures:
   - Deterministic, typed prompt assembly injecting pre-resolved Homelab coordinates
     (`/srv/mergerfs/pool_koda/docker_data/<stack>`, `kodak-net`, `mem_limit` for OMV's 7.6 GiB RAM,
     and `@Kodak-ri` repositories) to zero out discovery token waste in `agy`.
"""

from typing import Any, Dict, List, Optional

# Canonical OMV Stacks Coordinate Map (Komodo GitOps + MergerFS Live Paths + Memory Budgets)
OMV_STACKS_CATALOG: Dict[str, Dict[str, Any]] = {
    "media-stack": {
        "aliases": ["media", "media-stack", "qbittorrent", "flaresolverr", "jellyfin", "navidrome", "sonarr", "radarr", "prowlarr"],
        "project_name": "media-stack",
        "live_path": "/srv/mergerfs/pool_koda/docker_data/media/",
        "gitops_file": "stacks-exemplo/media.yml",
        "network": "kodak-net (external: true)",
        "mem_limits": "qbittorrent: 2048m (res: 512m), jellyfin: 2048m, flaresolverr: 512m, *arr/navidrome: 256m-512m",
        "ports": "8080 (qBittorrent), 8096 (Jellyfin), 4533 (Navidrome), 9696 (Prowlarr), 7878 (Radarr), 8989 (Sonarr)",
    },
    "ts": {
        "aliases": ["ts", "teamspeak", "teamspeak6"],
        "project_name": "ts",
        "live_path": "/srv/mergerfs/pool_koda/docker_data/TS/",
        "gitops_file": "stacks-exemplo/ts.yml",
        "network": "kodak-net (external: true)",
        "mem_limits": "teamspeak: 512m (res: 128m) | TSSERVER_LICENSE_ACCEPTED=accept",
        "ports": "9987/udp, 30033/tcp",
    },
    "tcc-bot": {
        "aliases": ["tcc-bot", "tcc", "ach", "heuer", "osint", "ri-bot"],
        "project_name": "tcc-bot",
        "live_path": "/srv/mergerfs/pool_koda/docker_data/tcc-bot/",
        "gitops_file": "stacks-exemplo/tcc-bot.yml",
        "network": "kodak-net (external: true)",
        "mem_limits": "tcc-bot: 512m (res: 128m) | Gunicorn WSGI non-root (UID 10001)",
        "ports": "5051/tcp (/api/health)",
    },
    "immich": {
        "aliases": ["immich", "immich2", "fotos", "vectorchord", "valkey"],
        "project_name": "immich",
        "live_path": "/srv/mergerfs/pool_koda/docker_data/immich/",
        "gitops_file": "stacks-exemplo/immich.yml",
        "network": "kodak-net (external: true)",
        "mem_limits": "immich-server: 1536m, immich-machine-learning: 1536m, database (VectorChord): 1024m, redis (Valkey): 256m",
        "ports": "2283/tcp",
    },
    "komodo": {
        "aliases": ["komodo", "ferretdb", "gitops", "periphery"],
        "project_name": "komodo",
        "live_path": "/srv/mergerfs/pool_koda/docker_data/komodo/",
        "gitops_file": "stacks-exemplo/komodo.yml",
        "network": "kodak-net (external: true)",
        "mem_limits": "komodo-core: 256m, komodo-ferretdb (v1 SQLite): 256m, komodo-periphery: 128m (~25.13 MiB uso real)",
        "ports": "9120/tcp",
    },
    "romm-stack": {
        "aliases": ["romm", "romm-stack", "roms", "retro"],
        "project_name": "romm-stack",
        "live_path": "/srv/mergerfs/pool_koda/docker_data/romm/",
        "gitops_file": "stacks-exemplo/romm.yml",
        "network": "kodak-net (external: true)",
        "mem_limits": "romm: 1024m, romm-db (MariaDB): 512m",
        "ports": "8082/tcp",
    },
    "jdownloader": {
        "aliases": ["jdownloader", "jdownloader2", "jd2"],
        "project_name": "jdownloader",
        "live_path": "/srv/mergerfs/pool_koda/docker_data/jdownloader/",
        "gitops_file": "stacks-exemplo/jdownloader.yml",
        "network": "kodak-net (external: true)",
        "mem_limits": "jdownloader: 1024m (res: 256m)",
        "ports": "5800/tcp",
    },
    "management": {
        "aliases": ["management", "homarr", "dashboard"],
        "project_name": "management",
        "live_path": "/srv/mergerfs/pool_koda/docker_data/management/",
        "gitops_file": "stacks-exemplo/management.yml",
        "network": "kodak-net (external: true)",
        "mem_limits": "homarr: 512m (res: 128m)",
        "ports": "7575/tcp",
    },
}

KODAK_GITHUB_REPOS = [
    ("Kodak-ri/maestro-orchestrator", "Orquestrador Híbrido v2.0 (Roteador Semântico, Memória Híbrida Hy-Memory & Meta-Prompter AGY)"),
    ("Kodak-ri/omv-relatorios-agente", "Diário de bordo, entregas (/work/entregas/), automação AGY Watcher e esteira CI"),
    ("Kodak-ri/omv-server-docs", "Fonte Única da Verdade GitOps do OMV 8.5 (DOCUMENTACAO_COMPLETA_OMV.md e stacks-exemplo/)"),
    ("Kodak-ri/kodak-homelab-projects", "Hardware Bazzite RTX 3060 Ti, Smart TV LG webOS (kodachi), Pocophone F1 e Archer C5"),
    ("Kodak-ri/tcc-bot", "Microsserviço autônomo ACH Heuer OSINT com Google Gemini e Gunicorn"),
    ("Kodak-ri/steam-indie-deals", "Monitor automatizado de promoções Indie na Steam com alertas por e-mail"),
    ("Kodak-ri/RI-BOT", "Repositório histórico de bots e automações (branch TCC sincronizada)"),
]


def resolve_canonical_stacks(query: str) -> List[Dict[str, Any]]:
    """Identifies which OMV Docker stacks are referenced in the user query."""
    q_low = query.lower()
    matched: List[Dict[str, Any]] = []
    for _key, meta in OMV_STACKS_CATALOG.items():
        if any(alias in q_low for alias in meta["aliases"]):
            matched.append(meta)
    return matched


def build_surgical_super_prompt(
    query: str,
    route_info: Dict[str, Any],
    rag_result: Optional[Dict[str, Any]] = None,
    episodic_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Compiles a structured, zero-waste Super-Prompt for the AGY Surgeon (`agy`)
    following the 5-Pillar Orca Task-Spec Contract + Pi Context Handoff + Hy-Memory Coordinates.
    """
    thinking = route_info.get("thinking", "medium").upper()
    reason = route_info.get("reason", "Intervenção de infraestrutura/governança.")
    stage = route_info.get("stage", "HYBRID_CASCADE")

    # 1. Resolve Canonical Stack Coordinates
    matched_stacks = resolve_canonical_stacks(query)
    if matched_stacks:
        stack_lines = []
        for st in matched_stacks:
            stack_lines.append(
                f"  - Projeto Compose (`name:`): `{st['project_name']}`\n"
                f"    • Pasta Viva no OMV: `{st['live_path']}`\n"
                f"    • Alvo GitOps (`omv-server-docs`): `{st['gitops_file']}`\n"
                f"    • Rede & Orçamento RAM (Host 7.6 GiB): `{st['network']}` | `{st['mem_limits']}`\n"
                f"    • Portas: `{st['ports']}`"
            )
        stacks_block = "\n".join(stack_lines)
    else:
        stacks_block = (
            "  - Raiz Canônica de Persistência no OMV: `/srv/mergerfs/pool_koda/docker_data/<stack>/`\n"
            "  - Rede Docker Obrigatória: `kodak-net` (`external: true` — nunca misturar com `network_mode: bridge`)\n"
            "  - Orçamento de Memória do Host OMV (`servidordokodak`): `7.6 GiB RAM física + 4.0 GiB Swapfile` (declarar `mem_limit` e `mem_reservation` em todo container)\n"
            "  - Identidade GitOps Komodo: preservar `name: <PROJECT_NAME_REAL>` em `Kodak-ri/omv-server-docs/stacks-exemplo/`"
        )

    # 2. Episodic Memory Continuity (Hy-Memory LAST 5 USER TURNS + Reusable Experiences)
    episodic_lines = []
    if episodic_context:
        comp_sum = episodic_context.get("compaction_summary", "").strip()
        if comp_sum:
            episodic_lines.append(f"  - Resumo Compactado (Pi Compaction): {comp_sum}")
        recent_facts = episodic_context.get("recent_facts", [])[-3:]
        for f in recent_facts:
            episodic_lines.append(
                f"  - Turno Recente [{f.get('scene', 'work')}/{f.get('route', '')}]: \"{f.get('query', '')[:90]}\""
            )
        for exp in episodic_context.get("experiences", [])[:2]:
            episodic_lines.append(
                f"  - Experiência Reutilizável ({exp['id']}): {exp['solution']}"
            )
    episodic_block = (
        "\n".join(episodic_lines)
        if episodic_lines
        else "  - Sessão limpa inicializada (sem dependências de turnos anteriores)."
    )

    # 3. Compressed Semantic RAG Block (LLMLingua + Hy-Memory Coordinate Compression)
    rag_text = (rag_result or {}).get("compressed_text", "").strip()
    rag_metrics = (rag_result or {}).get("metrics", {})
    if rag_text:
        saved_info = (
            f" (Compressão Híbrida: {rag_metrics.get('raw_chars', 0)} ➔ {rag_metrics.get('compressed_chars', 0)} chars | "
            f"-{rag_metrics.get('saved_pct', 0)}% tokens)"
            if rag_metrics
            else ""
        )
        rag_block = f"### 4. Contexto Semântico Comprimido{saved_info}\n{rag_text}\n"
    else:
        rag_block = (
            "### 4. Contexto Semântico Base\n"
            "• Fonte Principal: `/work/DOCUMENTACAO_COMPLETA_OMV.md` & `/work/AGENTS.md`\n"
        )

    repos_summary = "\n".join(
        f"  - `{repo}`: {desc}" for repo, desc in KODAK_GITHUB_REPOS[:6]
    )

    super_prompt = (
        "# 🩺 SUPER-PROMPT CIRÚRGICO MAESTRO v2.0 (ORCA TASK-SPEC CONTRACT)\n\n"
        "### 1. Papel, Autoridade e Orçamento Cognitivo (`Role & Thinking Budget`)\n"
        "- **Agente Executor:** Cirurgião `agy` operando em modo de autonomia total (`accept-edits / zero perguntas`).\n"
        f"- **Nível de Raciocínio Recomendado (`Thinking Level`):** `{thinking}`\n"
        f"- **Diagnóstico do Roteador ({stage}):** {reason}\n\n"
        "### 2. Objetivo da Missão & Memória Episódica (`Target & Working Memory`)\n"
        f"- **Objetivo Principal:**\n  > {query}\n"
        f"- **Continuidade Episódica (Hy-Memory Working Facts & Experiences):**\n{episodic_block}\n\n"
        "### 3. Coordenadas Canônicas Já Resolvidas (`Resolved Canonical Coordinates`)\n"
        f"{stacks_block}\n"
        "- **Ecossistema de Repositórios `@Kodak-ri`:**\n"
        f"{repos_summary}\n\n"
        f"{rag_block}\n"
        "### 5. Restrições Estritas de Segurança (`Safety & Governance Floor`)\n"
        "1. **Escopo de Escrita Local:** Trabalhe exclusivamente em `/work`. **JAMAIS** escreva ou altere nada diretamente no host do OMV (`servidordokodak`).\n"
        "2. **Diagnóstico Read-Only no OMV:** Use estritamente `ssh omv 'sudo agente-ler <ls|cat|grep|find|du|df|free|uptime|ps|journal>'` e `ssh omv 'sudo agente-docker <ps|stats|logs|inspect|network|volume>'`.\n"
        "3. **Homologação Isolada na `labvm`:** Toda nova stack ou ajuste de container deve ser validado via `ssh labvm` com caminhos adaptados, segredos fictícios e container `Up` por ≥ 60s.\n"
        "4. **Sanitização Absoluta:** Mascarar IPs, domínios, senhas e tokens reais com `<IP_SERVIDOR>`, `<IP_LAN>`, `<IP_TAILSCALE>`, `<DOMINIO>`, `<SENHA>`, `<TOKEN>`.\n\n"
        "### 6. Critérios de Aceite Observáveis (`Observable Acceptance Criteria`)\n"
        "- [ ] Evidências reais coletadas e testes executados sem erros fatais.\n"
        "- [ ] Entrega documentada em `/work/entregas/YYYY-MM-DD_<tarefa>/RELATORIO_PARA_IA.md` (6 seções obrigatórias) + cópia em `/work/entregas/ULTIMO_RELATORIO.md`.\n"
        "- [ ] Atualização sincronizada de `/work/entregas/STATUS_PROPOSTAS.md` e `/work/README.md`.\n"
        "- [ ] Varredura anti-vazamento (`grep -E`) limpa antes de `git commit` e `git push`."
    )
    return super_prompt
