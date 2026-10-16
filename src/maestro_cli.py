#!/usr/bin/env python3
"""
Maestro v2.0 — Orquestrador Semântico Híbrido, Memória Dual & Construtor de Super-Prompts
==========================================================================================
Ambiente: Host Bazzite Linux (RTX 3060 Ti 8GB) + Container Agente + Servidor OMV
Repositório Oficial: https://github.com/Kodak-ri/maestro-orchestrator

Arquitetura v2.0 baseada nas referências estudadas:
  • stablyai/orca         -> Task-Spec Contract (5 Pilares) & Orquestração Determinística
  • earendil-works/pi     -> Minimalismo CLI, Virtual Models, Session Compaction & Context Handoff
  • tencent/Hy-Memory     -> Dual-System Hybrid Memory (WorkingFact + Experience) & Selective Retention
  • RouteLLM & Aurelio    -> Roteamento Semântico em Cascata (< 50ms) por Centroides de Intenção
  • LLMLingua & DSPy      -> Compressão de Contexto por Densidade de Coordenadas e Meta-Prompting
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# Garante que o pacote `src` do Maestro v2.0 seja encontrado tanto via symlink
# (/usr/local/bin/maestro -> /work/automacao/maestro.py) quanto no repositório
MAESTRO_REPO_ROOT = "/work/maestro-orchestrator"
for candidate in [
    str(Path(__file__).resolve().parent.parent),
    MAESTRO_REPO_ROOT,
    "/work/automacao",
]:
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.memory import HybridMemoryManager
from src.router import HybridCascadeRouter
from src.super_prompt import build_surgical_super_prompt, resolve_canonical_stacks

# Tenta carregar integração GitHub do OMV se disponível
try:
    if "/work/automacao" not in sys.path:
        sys.path.append("/work/automacao")
    import omv_github
except ImportError:
    omv_github = None

# Configurações de Ambiente e Endpoints
VERSION = "2.0.0"
OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://host.containers.internal:11434")
DEFAULT_MODEL = os.environ.get("MAESTRO_LOCAL_MODEL", "kodak-coder:latest")
FALLBACK_LOCAL_MODEL = os.environ.get("MAESTRO_FALLBACK_LOCAL_MODEL", "qwen2.5-coder:7b")
EMBED_MODEL = os.environ.get("MAESTRO_EMBED_MODEL", "nomic-embed-text:latest")
OPENCODE_MODEL = os.environ.get("MAESTRO_OPENCODE_MODEL", "opencode/deepseek-v4.1-flash-free")
OPENWEBUI_PORTS = [8080, 3000]

# Cores ANSI para Terminal
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_BLUE = "\033[94m"
C_MAGENTA = "\033[95m"
C_GRAY = "\033[90m"


# ==============================================================================
# 1. DIAGNÓSTICO E STATUS DO ECOSSISTEMA HOMELAB
# ==============================================================================

def get_ollama_status() -> Dict[str, Any]:
    """Consulta Ollama e métricas de VRAM da GPU RTX 3060 Ti."""
    t0 = time.time()
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/ps")
        with urllib.request.urlopen(req, timeout=2.0) as r:
            ps_data = json.loads(r.read().decode())
        latency_ms = int((time.time() - t0) * 1000)

        req_tags = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req_tags, timeout=2.0) as r_tags:
            tags_data = json.loads(r_tags.read().decode())

        return {
            "online": True,
            "latency_ms": latency_ms,
            "loaded_models": ps_data.get("models", []),
            "available_models": [m["name"] for m in tags_data.get("models", [])],
        }
    except Exception as e:
        return {
            "online": False,
            "error": str(e),
            "latency_ms": 0,
            "loaded_models": [],
            "available_models": [],
        }


def check_openwebui() -> Dict[int, str]:
    """Verifica se Open WebUI está respondendo nas portas 8080 ou 3000."""
    status = {}
    for port in OPENWEBUI_PORTS:
        url = f"http://host.containers.internal:{port}"
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                status[port] = f"ONLINE (HTTP {resp.status})"
        except urllib.error.HTTPError as e:
            status[port] = f"ONLINE (HTTP {e.code})"
        except Exception:
            status[port] = "INATIVO / FECHADO"
    return status


def check_opencode_cli() -> Dict[str, Any]:
    """Verifica versão e configuração do OpenCode."""
    try:
        res = subprocess.run(
            ["opencode", "--version"], capture_output=True, text=True, timeout=3
        )
        version = res.stdout.strip() if res.returncode == 0 else None
    except Exception:
        version = None

    config_model = OPENCODE_MODEL
    config_file = "/work/.opencode.json"
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                c = json.load(f)
                config_model = c.get("model", OPENCODE_MODEL)
        except Exception:
            pass

    return {
        "installed": version is not None,
        "version": version or "Não instalado",
        "model": config_model,
    }


def check_agy_status() -> Dict[str, Any]:
    """Verifica status do AGY CLI e do daemon agy-watcher."""
    try:
        res = subprocess.run(
            ["agy", "--version"], capture_output=True, text=True, timeout=3
        )
        agy_ver = res.stdout.strip() if res.returncode == 0 else "Instalado"
    except Exception:
        agy_ver = "Não instalado"

    res_ps = subprocess.run(
        ["pgrep", "-f", "[a]gy-watcher.py"], capture_output=True, text=True
    )
    watcher_running = res_ps.returncode == 0
    watcher_pid = res_ps.stdout.strip().replace("\n", ",") if watcher_running else None

    token_ok = False
    if omv_github:
        try:
            token_ok = bool(omv_github.get_token())
        except Exception:
            pass

    return {
        "agy_ver": agy_ver,
        "watcher_running": watcher_running,
        "watcher_pid": watcher_pid,
        "github_token": token_ok,
    }


def check_hosts_connectivity() -> Dict[str, str]:
    """Verifica conectividade SSH com OMV e LabVM."""
    res_omv = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=2", "omv", "echo ok"],
        capture_output=True,
        text=True,
    )
    omv_online = res_omv.returncode == 0

    res_lab = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=2", "labvm", "echo ok"],
        capture_output=True,
        text=True,
    )
    lab_online = res_lab.returncode == 0

    return {
        "omv": "ONLINE" if omv_online else "OFFLINE (Tailscale/SSH fechado)",
        "labvm": "ONLINE" if lab_online else "OFFLINE",
    }


def print_status_dashboard(memory_mgr: HybridMemoryManager) -> None:
    """Renderiza painel visual consolidado do Maestro v2.0."""
    print(f"\n{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════════════════════════════════╗{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}║       👑 MAESTRO ORCHESTRATOR v{VERSION} — STATUS DO ECOSSISTEMA HÍBRIDO     ║{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}╚══════════════════════════════════════════════════════════════════════════╝{C_RESET}")

    # 1. Ollama & GPU
    ollama = get_ollama_status()
    print(f"\n{C_BOLD}[1] GPU HOST (Bazzite Linux & NVIDIA RTX 3060 Ti 8GB):{C_RESET}")
    if ollama["online"]:
        print(f"  • Endpoint Ollama:     {C_GREEN}ONLINE{C_RESET} ({OLLAMA_BASE} - latência: {ollama['latency_ms']}ms)")
        vram_models = ollama["loaded_models"]
        if vram_models:
            for m in vram_models:
                vram_gb = m.get("size_vram", 0) / (1024**3)
                print(
                    f"  • Modelo Ativo na VRAM:{C_BOLD}{C_GREEN} {m['name']}{C_RESET} "
                    f"({vram_gb:.2f} GB na VRAM | Runner: {m.get('runner', 'llamacpp')})"
                )
        else:
            print(f"  • Modelos na VRAM:     {C_YELLOW}Nenhum modelo retido no momento (carregamento sob demanda){C_RESET}")
        print(f"  • Modelos Disponíveis: {', '.join(ollama['available_models'])}")
    else:
        print(
            f"  • Endpoint Ollama:     {C_YELLOW}MODO JOGO / PAUSADO{C_RESET} "
            f"(Auto-Fallback para OpenCode Worker ativo)"
        )

    # 2. Roteador Híbrido & Memória Hy-Memory
    wf_count = len(memory_mgr.state.get("working_facts", []))
    exp_count = len(memory_mgr.state.get("experiences", []))
    comp_count = memory_mgr.state.get("compactions_count", 0)
    avail_docs = sum(1 for d in memory_mgr.rag_docs if os.path.exists(d))
    print(f"\n{C_BOLD}[2] ARQUITETURA MAESTRO v2.0 (Cascade Router + Hy-Memory):{C_RESET}")
    print(f"  • Roteador em Cascata: {C_GREEN}ATIVO{C_RESET} (Stage 1 Heuristic <1ms | Stage 2 Vector <45ms | Stage 3 LLM)")
    print(
        f"  • Memória Episódica:   {C_CYAN}{wf_count} WorkingFacts{C_RESET} | "
        f"{C_CYAN}{exp_count} Experiences{C_RESET} | {comp_count} Compactações ({memory_mgr.memory_file})"
    )
    print(
        f"  • Memória Semântica:   {C_GREEN}{avail_docs}/{len(memory_mgr.rag_docs)} docs RAG locais{C_RESET} "
        f"+ Base Homelab Curada (Compressão LLMLingua/Hy-Memory)"
    )

    # 3. OpenCode
    oc = check_opencode_cli()
    print(f"\n{C_BOLD}[3] OPENCODE WORKER (Fallback Zero-Custo & Multi-File):{C_RESET}")
    print(f"  • Binário CLI:         {C_GREEN if oc['installed'] else C_RED}{oc['version']}{C_RESET}")
    print(f"  • Modelo Padrão:       {C_CYAN}{oc['model']}{C_RESET}")

    # 4. Open WebUI
    owui = check_openwebui()
    print(f"\n{C_BOLD}[4] OPEN WEBUI (Host Bazzite):{C_RESET}")
    for port, st in owui.items():
        color = C_GREEN if "ONLINE" in st else C_GRAY
        print(f"  • Porta {port}:           {color}{st}{C_RESET}")

    # 5. AGY & Automação GitHub
    agy_st = check_agy_status()
    print(f"\n{C_BOLD}[5] CIRURGIÃO AGY & GITOPS:{C_RESET}")
    print(f"  • AGY CLI:             {C_GREEN if 'Não' not in agy_st['agy_ver'] else C_RED}{agy_st['agy_ver']}{C_RESET}")
    watcher_str = (
        f"{C_GREEN}EM EXECUÇÃO (PID {agy_st['watcher_pid']}){C_RESET}"
        if agy_st["watcher_running"]
        else f"{C_YELLOW}PRONTO (Aguardando acionamento / agy-watcher.py){C_RESET}"
    )
    print(f"  • Watcher de Issues:   {watcher_str}")
    print(
        f"  • Token GitHub:        "
        f"{C_GREEN if agy_st['github_token'] else C_RED}"
        f"{'CONFIGURADO (API Pronta)' if agy_st['github_token'] else 'NÃO DETECTADO'}{C_RESET}"
    )

    # 6. Servidores OMV e LabVM
    conn = check_hosts_connectivity()
    print(f"\n{C_BOLD}[6] CONECTIVIDADE DE HOSTS EXTERNOS:{C_RESET}")
    omv_color = C_GREEN if "ONLINE" in conn["omv"] else C_YELLOW
    lab_color = C_GREEN if "ONLINE" in conn["labvm"] else C_GRAY
    print(f"  • OMV (servidordokodak): {omv_color}{conn['omv']}{C_RESET}")
    print(f"  • LabVM (Debian 13 Lab): {lab_color}{conn['labvm']}{C_RESET}")

    # 7. Smart TV LG / Hardware
    kodachi_bin = os.path.exists("/usr/local/bin/kodachi-ctl")
    kodachi_key = os.path.exists("/home/Kodak/agente-home/.kodachi-key")
    print(f"\n{C_BOLD}[7] HARDWARE & SMART TV LG (webOS):{C_RESET}")
    print(f"  • kodachi-ctl:         {C_GREEN if kodachi_bin else C_RED}{'Pronto (/usr/local/bin/kodachi-ctl)' if kodachi_bin else 'Ausente'}{C_RESET}")
    print(
        f"  • Handshake SSAP:      "
        f"{C_GREEN if kodachi_key else C_YELLOW}"
        f"{'Autenticado (.kodachi-key presente)' if kodachi_key else 'Pendente (execute kodachi-ctl pair)'}{C_RESET}"
    )

    print(f"\n{C_BOLD}{C_CYAN}══════════════════════════════════════════════════════════════════════════{C_RESET}\n")


# ==============================================================================
# 2. EXECUÇÃO DOS WORKERS (GPU LOCAL, HOMELAB RAG, OPENCODE & CIRURGIÃO AGY)
# ==============================================================================

def print_route_explanation(decision: Dict[str, Any]) -> None:
    """Exibe cartão de diagnóstico detalhado do Roteador Híbrido v2.0."""
    print(f"\n{C_BOLD}{C_CYAN}┌──────────────────────────────────────────────────────────────────────────┐{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}│           🧭 MAESTRO v2.0 — DIAGNÓSTICO DE ROTEAMENTO HÍBRIDO            │{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}└──────────────────────────────────────────────────────────────────────────┘{C_RESET}")
    print(f"  • Rota Selecionada:   {C_BOLD}{C_GREEN}{decision['route']}{C_RESET}")
    print(f"  • Estágio Decisor:    {C_CYAN}{decision['stage']}{C_RESET} ({decision['latency_ms']:.2f} ms)")
    print(f"  • Confiança:          {C_YELLOW}{decision['confidence']:.3f}{C_RESET}")
    print(f"  • Thinking Level:     {C_BOLD}{C_MAGENTA}{decision['thinking'].upper()}{C_RESET}")
    print(f"  • Justificativa:      {decision['reason']}")
    telemetry = decision.get("telemetry", {})
    h_scores = telemetry.get("heuristic", {}).get("scores", {})
    s_scores = telemetry.get("semantic", {}).get("all_similarities", {})
    if h_scores:
        h_str = ", ".join(f"{k}={v:.2f}" for k, v in sorted(h_scores.items(), key=lambda x: x[1], reverse=True))
        print(f"  • Scores Estágio 1:   {C_GRAY}{h_str}{C_RESET}")
    if s_scores:
        s_str = ", ".join(f"{k}={v:.3f}" for k, v in sorted(s_scores.items(), key=lambda x: x[1], reverse=True))
        print(f"  • Cosine Estágio 2:   {C_GRAY}{s_str}{C_RESET}")
    print(f"{C_GRAY}──────────────────────────────────────────────────────────────────────────{C_RESET}")


def execute_opencode_fallback(query: str, compressed_rag: str = "", reason_label: str = "OPENCODE_WORKER") -> str:
    """
    Executa a tarefa diretamente via OpenCode CLI (`opencode run -m opencode/deepseek-v4.1-flash-free`)
    quando a rota é OPENCODE_WORKER ou quando o Ollama local está em Modo Jogo.
    """
    print(f"\n{C_BOLD}{C_BLUE}💻 [{reason_label}] Executando via OpenCode CLI ({OPENCODE_MODEL})...{C_RESET}\n")
    prompt_parts = [
        "Você é o Kodak Coder / Maestro v2.0, especialista em Linux Debian, Docker, Python, Bash e Homelab OMV.",
        "Responda de forma técnica, direta, enxuta e pronta para produção. Mantenha sanitização rigorosa (<IP_SERVIDOR>, <SENHA>).",
    ]
    if compressed_rag:
        prompt_parts.append(f"\n[CONTEXTO HOMELAB COMPRIMIDO (HY-MEMORY)]:\n{compressed_rag}")
    prompt_parts.append(f"\nPedido do Usuário:\n{query}")
    full_prompt = "\n".join(prompt_parts)

    t0 = time.time()
    try:
        proc = subprocess.run(
            ["opencode", "run", "-m", OPENCODE_MODEL, full_prompt],
            capture_output=True,
            text=True,
            timeout=90,
            cwd="/work",
        )
        elapsed = time.time() - t0
        output = (proc.stdout or "").strip()
        if not output and proc.stderr:
            output = proc.stderr.strip()

        if output:
            print(output)
            est_tokens = max(1, len(output) // 4)
            tps = est_tokens / elapsed if elapsed > 0 else 0.0
            print(f"\n{C_GRAY}──────────────────────────────────────────────────────────────────────────{C_RESET}")
            print(f"{C_BOLD}{C_BLUE}⚡ Execução Concluída via OpenCode Worker ({OPENCODE_MODEL}){C_RESET}")
            print(f"  • Métricas: ~{C_BOLD}{est_tokens} tokens{C_RESET} em {C_BOLD}{elapsed:.2f}s{C_RESET} (~{C_BOLD}{tps:.1f} tokens/s{C_RESET})")
            print(f"  • Custo de Cota AGY: {C_BOLD}$0.00 (Zero tokens consumidos do Cirurgião){C_RESET}")
            print(f"{C_GRAY}──────────────────────────────────────────────────────────────────────────{C_RESET}\n")
            return output
    except Exception as e:
        print(f"{C_YELLOW}[AVISO] OpenCode CLI não respondeu a tempo ({e}). Exibindo comando manual:{C_RESET}")

    print(f"  • Comando Sugerido: {C_BOLD}opencode run -m {OPENCODE_MODEL} \"{query}\"{C_RESET}\n")
    return f"Encaminhado ao OpenCode CLI ({OPENCODE_MODEL})."


def execute_local_worker(
    query: str,
    memory_mgr: HybridMemoryManager,
    rag_result: Dict[str, Any],
    route_name: str = "WORKER_LOCAL_GPU",
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Executa a geração completa no modelo local da RTX 3060 Ti com streaming em tempo real,
    injetando a Memória Híbrida comprimida (Hy-Memory) e exibindo métricas de velocidade.
    Caso o Ollama esteja pausado (Modo Jogo no Bazzite), aciona fallback automático no OpenCode.
    """
    compressed_rag = rag_result.get("compressed_text", "")
    comp_metrics = rag_result.get("metrics", {})
    episodic = memory_mgr.get_episodic_context(query)

    if comp_metrics.get("raw_est_tokens", 0) > 0:
        print(
            f"{C_BOLD}{C_CYAN}🧠 [Hy-Memory Compressor]{C_RESET} "
            f"RAG compactado: {comp_metrics['raw_est_tokens']} -> {comp_metrics['compressed_est_tokens']} tokens "
            f"({C_GREEN}-{comp_metrics['saved_pct']}% de economia{C_RESET})"
        )

    print(f"\n{C_BOLD}{C_GREEN}⚡ [{route_name}] Processando na RTX 3060 Ti via '{model}'...{C_RESET}\n")

    system_instruction = (
        "Você é o Kodak Coder (Maestro v2.0), assistente sênior especialista em Linux Debian, "
        "Docker Compose, Python, Bash, WebOS e Homelab OMV.\n"
        "Forneça respostas técnicas diretas, código limpo, scripts robustos e prontos para produção.\n"
        "Nunca invente parâmetros não existentes e mantenha sanitização rigorosa (<IP_SERVIDOR>, <SENHA>)."
    )

    context_blocks = [system_instruction]
    if episodic.get("recent_facts"):
        ep_lines = ["[MEMÓRIA EPISÓDICA RECENTE (HY-MEMORY)]:"]
        for f in episodic["recent_facts"][-3:]:
            ep_lines.append(f"- [{f.get('route')}]: {f.get('query', '')[:90]}")
        context_blocks.append("\n".join(ep_lines))
    if compressed_rag:
        context_blocks.append(f"[CONTEXTO HOMELAB COMPRIMIDO]:\n{compressed_rag}")
    context_blocks.append(f"[PEDIDO DO USUÁRIO]:\n{query}\n\n[RESPOSTA]:\n")
    full_prompt = "\n\n".join(context_blocks)

    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": True,
    }

    t0 = time.time()
    collected_chunks: List[str] = []
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        eval_count = 0
        eval_duration = 0.0

        with urllib.request.urlopen(req, timeout=15.0) as resp:
            for line in resp:
                if not line.strip():
                    continue
                chunk = json.loads(line.decode("utf-8"))
                token_str = chunk.get("response", "")
                collected_chunks.append(token_str)
                sys.stdout.write(token_str)
                sys.stdout.flush()

                if chunk.get("done"):
                    eval_count = chunk.get("eval_count", 0)
                    eval_duration = chunk.get("eval_duration", 0) / 1e9

        print("\n")
        elapsed = time.time() - t0
        if eval_count == 0:
            eval_count = max(1, len("".join(collected_chunks)) // 4)
        tps = eval_count / eval_duration if eval_duration > 0 else (eval_count / elapsed if elapsed > 0 else 0.0)
        print(f"{C_GRAY}──────────────────────────────────────────────────────────────────────────{C_RESET}")
        print(f"{C_BOLD}{C_GREEN}⚡ Execução Concluída com Sucesso na RTX 3060 Ti ({model}){C_RESET}")
        print(
            f"  • Métricas: {C_BOLD}{eval_count} tokens{C_RESET} gerados em "
            f"{C_BOLD}{elapsed:.2f}s{C_RESET} (~{C_BOLD}{tps:.1f} tokens/s{C_RESET})"
        )
        print(f"  • Cota Externa / AGY: {C_BOLD}$0.00 (Zero tokens consumidos na nuvem){C_RESET}")
        print(f"{C_GRAY}──────────────────────────────────────────────────────────────────────────{C_RESET}\n")
        return "".join(collected_chunks).strip()

    except Exception as e:
        print(
            f"{C_YELLOW}[!] Ollama local indisponível ({e}) — Host Bazzite possivelmente em Modo Jogo.{C_RESET}"
        )
        print(f"{C_CYAN}[*] Acionando Auto-Fallback Resiliente para OpenCode Worker...{C_RESET}")
        return execute_opencode_fallback(query, compressed_rag=compressed_rag, reason_label=f"{route_name} -> OPENCODE_FALLBACK")


def execute_agy_surgeon(
    query: str,
    memory_mgr: HybridMemoryManager,
    rag_result: Dict[str, Any],
    decision: Dict[str, Any],
    run_agy: bool = False,
    make_issue: bool = False,
) -> str:
    """
    Compila o Super-Prompt de 5 Pilares (Orca + Pi + Hy-Memory) para o Cirurgião AGY,
    com suporte a disparo direto (--run-agy) ou abertura de Issue GitOps (--issue).
    """
    episodic_ctx = memory_mgr.get_episodic_context(query)
    stacks_detected = resolve_canonical_stacks(query)
    comp_metrics = rag_result.get("metrics", {})

    super_prompt = build_surgical_super_prompt(
        query=query,
        route_info=decision,
        rag_result=rag_result,
        episodic_context=episodic_ctx,
    )

    print(f"\n{C_BOLD}{C_MAGENTA}🩺 [CIRURGIÃO_AGY] Tarefa de Infraestrutura / Diagnóstico / GitOps Detectada{C_RESET}")
    print(f"  • Estágio do Router:      {C_CYAN}{decision['stage']}{C_RESET} ({decision['latency_ms']:.2f} ms | conf={decision['confidence']:.2f})")
    print(f"  • Motivo da Triagem:      {C_CYAN}{decision['reason']}{C_RESET}")
    print(f"  • Nível de Thinking Rec.: {C_BOLD}{C_YELLOW}{decision['thinking'].upper()}{C_RESET}")
    if stacks_detected:
        print(
            f"  • Stacks Pré-Resolvidas:  {C_GREEN}{', '.join(s['project_name'] for s in stacks_detected)}{C_RESET}"
        )
    if comp_metrics.get("raw_est_tokens", 0) > 0:
        print(
            f"  • Compressão Hy-Memory:   {comp_metrics['raw_est_tokens']} -> {comp_metrics['compressed_est_tokens']} tokens "
            f"({C_GREEN}-{comp_metrics['saved_pct']}% de economia{C_RESET})\n"
        )
    else:
        print()

    print(f"{C_BOLD}┌──────────────────────────────────────────────────────────────────────────┐{C_RESET}")
    print(f"{C_BOLD}│         SUPER-PROMPT CIRÚRGICO v2.0 (ORCA + PI + HY-MEMORY)              │{C_RESET}")
    print(f"{C_BOLD}└──────────────────────────────────────────────────────────────────────────┘{C_RESET}")
    print(f"{C_CYAN}{super_prompt}{C_RESET}")
    print(f"{C_BOLD}────────────────────────────────────────────────────────────────────────────{C_RESET}\n")

    if run_agy:
        print(f"{C_BOLD}{C_YELLOW}[*] Flag --run-agy detectada! Disparando AGY CLI em modo autônomo...{C_RESET}")
        cmd = [
            "agy",
            "--dangerously-skip-permissions",
            "-p",
            super_prompt,
            "--mode",
            "auto",
        ]
        try:
            subprocess.run(cmd, cwd="/work")
        except Exception as e:
            print(f"{C_RED}[ERRO] Falha ao disparar AGY: {e}{C_RESET}")

    elif make_issue:
        print(f"{C_BOLD}{C_YELLOW}[*] Flag --issue detectada! Registrando ocorrência no GitHub...{C_RESET}")
        if omv_github:
            titulo = f"[MAESTRO v2] {query[:60]}..."
            corpo = (
                f"### Ocorrência Encaminhada pelo Maestro Orquestrador v{VERSION}\n\n"
                f"**Pedido Original:**\n{query}\n\n"
                f"**Roteamento:** `{decision['route']}` via `{decision['stage']}` ({decision['latency_ms']:.2f}ms) | "
                f"**Thinking:** `{decision['thinking'].upper()}`\n\n"
                f"**Super-Prompt Cirúrgico:**\n```markdown\n{super_prompt}\n```"
            )
            try:
                res = omv_github.criar_issue(titulo, corpo, labels=["agy:novo"])
                print(f"{C_GREEN}✅ Issue #{res.get('number')} criada com sucesso com rótulo 'agy:novo'!{C_RESET}")
                print(f"   URL: {res.get('html_url')}")
            except Exception as e:
                print(f"{C_RED}[ERRO] Falha ao criar Issue no GitHub: {e}{C_RESET}")
        else:
            print(f"{C_RED}[ERRO] Módulo omv_github indisponível.{C_RESET}")
    else:
        print(f"{C_GRAY}Dica: Para disparar o AGY automaticamente, use {C_BOLD}maestro --run-agy \"{query}\"{C_RESET}")
        print(f"{C_GRAY}Ou para criar Issue na fila de automação: {C_BOLD}maestro --issue \"{query}\"{C_RESET}\n")

    return super_prompt


# ==============================================================================
# 3. DIAGNÓSTICO DE MEMÓRIA HÍBRIDA & BENCHMARK SUITE
# ==============================================================================

def print_memory_dashboard(memory_mgr: HybridMemoryManager, compact: bool = False) -> None:
    """Exibe estado da Memória Híbrida (WorkingFact + Episodic Experience + Semantic RAG)."""
    if compact:
        comp_res = memory_mgr.compact_episodic_memory(keep_recent=4)
        print(f"\n{C_BOLD}{C_GREEN}🗜️ [Pi + Hy-Memory Compaction]{C_RESET} Resultado: {comp_res}")

    facts = memory_mgr.state.get("working_facts", [])
    experiences = memory_mgr.state.get("experiences", [])
    comp_summary = memory_mgr.state.get("compaction_summary", "")

    print(f"\n{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════════════════════════════════╗{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}║          🧠 MAESTRO v2.0 — ARQUITETURA DE MEMÓRIA HÍBRIDA (HY-MEMORY)    ║{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}╚══════════════════════════════════════════════════════════════════════════╝{C_RESET}")
    print(f"  • Arquivo Persistente:  {memory_mgr.memory_file}")
    print(f"  • WorkingFacts Ativos:  {C_BOLD}{len(facts)}{C_RESET}")
    print(f"  • Experiences (Longa):  {C_BOLD}{len(experiences)}{C_RESET}")
    print(f"  • Compactações Pi:      {C_BOLD}{memory_mgr.state.get('compactions_count', 0)}{C_RESET}")

    if comp_summary:
        print(f"\n{C_BOLD}🗜️ Resumo Compactado (Pi Compaction):{C_RESET}")
        print(f"  {C_GRAY}{comp_summary}{C_RESET}")

    if experiences:
        print(f"\n{C_BOLD}📌 Experiences Reutilizáveis (Hy-Memory Long-Term):{C_RESET}")
        for exp in experiences:
            print(f"  • {C_CYAN}{exp['id']}{C_RESET} (conf={exp['confidence']}): {exp['task_pattern']}")

    if facts:
        print(f"\n{C_BOLD}🕒 Últimos WorkingFacts (Turnos Recentes):{C_RESET}")
        for f in facts[-5:]:
            print(
                f"  • [{f.get('timestamp')}] {C_GREEN}{f.get('route')}{C_RESET} "
                f"(scene={f.get('scene')}, thinking={f.get('thinking')}): {f.get('query', '')[:65]}"
            )
    print()


def run_benchmark_suite(router: HybridCascadeRouter, memory_mgr: HybridMemoryManager) -> None:
    """Executa bateria de testes reais de roteamento (<50ms), compressão de contexto e geração."""
    print(f"\n{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════════════════════════════════╗{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}║         🚀 MAESTRO v2.0 — BENCHMARK DE ROTEAMENTO & HY-MEMORY RAG        ║{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}╚══════════════════════════════════════════════════════════════════════════╝{C_RESET}\n")

    test_cases = [
        ("Escreva uma função em Python para validar endereços IPv4 com regex e testes unitários", "WORKER_LOCAL_GPU"),
        ("Refatore múltiplos arquivos do projeto usando opencode e compare benchmarks no HuggingFace", "OPENCODE_WORKER"),
        ("Qual a configuração atual de RAM, swap e containers da media-stack no nosso homelab OMV?", "HOMELAB_RAG"),
        ("Conecte via ssh labvm, homologue o compose da stack romm-stack e faça git push para deploy no Komodo", "CIRURGIAO_AGY"),
    ]

    latencies = []
    hits = 0
    for query, expected in test_cases:
        dec = router.route(query)
        latencies.append(dec["latency_ms"])
        ok = dec["route"] == expected
        if ok:
            hits += 1
        badge = f"{C_GREEN}PASS{C_RESET}" if ok else f"{C_RED}FAIL{C_RESET}"
        print(
            f"  [{badge}] Esperado: {C_BOLD}{expected:<16}{C_RESET} | Obtido: {C_CYAN}{dec['route']:<16}{C_RESET} "
            f"| Stage: {dec['stage']:<24} | Latência: {C_YELLOW}{dec['latency_ms']:.2f} ms{C_RESET} | Thinking: {dec['thinking']}"
        )

    avg_lat = sum(latencies) / len(latencies)
    rag_res = memory_mgr.retrieve_semantic_rag(
        "Configuração do MergerFS pool_koda, RAM de 7.6 GiB e containers Docker no OMV",
        max_sections=3,
        max_chars_budget=1400,
    )
    comp_stats = rag_res.get("metrics", {})

    print(f"\n{C_BOLD}📊 Resumo das Métricas Maestro v2.0:{C_RESET}")
    print(f"  • Acurácia de Roteamento:   {C_GREEN}{hits}/{len(test_cases)} ({hits * 100 // len(test_cases)}%){C_RESET}")
    print(f"  • Latência Média de Triagem:{C_YELLOW} {avg_lat:.2f} ms{C_RESET} (Alvo < 50.00 ms)")
    print(
        f"  • Compressão Hy-Memory RAG: {C_CYAN}{comp_stats.get('raw_est_tokens', 0)} -> {comp_stats.get('compressed_est_tokens', 0)} tokens{C_RESET} "
        f"({C_GREEN}-{comp_stats.get('saved_pct', 0)}% de redução de tokens{C_RESET})"
    )
    print()


# ==============================================================================
# 4. FUNÇÃO PRINCIPAL / CLI
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Maestro v{VERSION} - Orquestrador Semântico Híbrido Homelab (GPU Local + Hy-Memory + OpenCode + Cirurgião AGY)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt", nargs="*", help="Pedido ou comando a ser orquestrado")
    parser.add_argument("--status", action="store_true", help="Exibe status completo dos modelos, GPU, Memória Híbrida, OpenCode, Open WebUI e servidores")
    parser.add_argument("--local", action="store_true", help="Força execução 100%% no modelo local da RTX 3060 Ti (ou fallback OpenCode)")
    parser.add_argument("--run-agy", action="store_true", help="Se for rota de infra, dispara automaticamente o AGY CLI")
    parser.add_argument("--issue", action="store_true", help="Se for rota de infra, abre uma Issue com rótulo 'agy:novo' no GitHub")
    parser.add_argument("--thinking", choices=["low", "medium", "high"], default=None, help="Sobrescreve o nível de raciocínio recomendado")
    parser.add_argument("--no-rag", action="store_true", help="Desativa injeção de contexto RAG local")
    parser.add_argument("--explain-route", action="store_true", help="Exibe diagnóstico detalhado dos 3 estágios do Roteador Híbrido")
    parser.add_argument("--super-prompt", action="store_true", help="Força a compilação e exibição do Super-Prompt Cirúrgico de 5 Pilares para o AGY")
    parser.add_argument("--memory", action="store_true", help="Exibe estatísticas e episódios da Memória Híbrida (WorkingFact + Episodic + RAG)")
    parser.add_argument("--compact-memory", action="store_true", help="Compacta episódios antigos da memória episódica em um resumo estruturado")
    parser.add_argument("--benchmark", action="store_true", help="Executa bateria de validação de latência (<50ms) e compressão de contexto")

    args = parser.parse_args()

    memory_mgr = HybridMemoryManager()
    router = HybridCascadeRouter(
        ollama_base=OLLAMA_BASE,
        llm_model=DEFAULT_MODEL,
        embed_model=EMBED_MODEL,
    )

    if args.status:
        print_status_dashboard(memory_mgr)
        return

    if args.memory or args.compact_memory:
        print_memory_dashboard(memory_mgr, compact=args.compact_memory)
        return

    if args.benchmark:
        run_benchmark_suite(router, memory_mgr)
        return

    query = " ".join(args.prompt).strip()
    if not query:
        parser.print_help()
        print(f"\n{C_YELLOW}Exemplos Maestro v{VERSION}:{C_RESET}")
        print('  maestro "Crie um script python para monitorar latência DNS"')
        print('  maestro --explain-route "Suba a stack romm-stack na labvm e faça git push"')
        print("  maestro --status | maestro --memory | maestro --benchmark\n")
        return

    # 1. Busca na Memória Longa / Semântica (RAG Híbrido com score de coordenadas)
    rag_result: Dict[str, Any] = {"sections": [], "compressed_text": "", "sources": [], "metrics": {}}
    if not args.no_rag:
        rag_result = memory_mgr.retrieve_semantic_rag(query, max_sections=2, max_chars_budget=1500)
        sections = rag_result.get("sections", [])
        if sections:
            print(f"{C_BOLD}{C_CYAN}📚 [Hy-Memory Semantic RAG]{C_RESET} {len(sections)} seção(ões) cirúrgica(s) localizada(s):")
            for item in sections:
                print(f"  • {item['file']} {C_GRAY}› {item['title']} (score={item['score']}){C_RESET}")

    # 2. Execução Forçada Local (--local)
    if args.local:
        out = execute_local_worker(query, memory_mgr, rag_result, route_name="WORKER_LOCAL_GPU")
        memory_mgr.record_turn(
            query=query,
            route="WORKER_LOCAL_GPU",
            thinking=args.thinking or "low",
            reason="Execução forçada via --local",
            sources=rag_result.get("sources", []),
        )
        return

    # 3. Roteamento Híbrido em Cascata (Fast Heuristic -> Semantic Vector -> LLM Fallback)
    ep_ctx = memory_mgr.get_episodic_context(query)
    decision = router.route(
        query=query,
        last_route=ep_ctx.get("last_route"),
    )
    if args.thinking:
        decision["thinking"] = args.thinking
    if args.super_prompt:
        decision["route"] = "CIRURGIAO_AGY"

    if args.explain_route:
        print_route_explanation(decision)

    # 4. Despacho para o Destino Selecionado
    if decision["route"] == "CIRURGIAO_AGY":
        out = execute_agy_surgeon(
            query=query,
            memory_mgr=memory_mgr,
            rag_result=rag_result,
            decision=decision,
            run_agy=args.run_agy,
            make_issue=args.issue,
        )
    elif decision["route"] == "OPENCODE_WORKER":
        out = execute_opencode_fallback(
            query,
            compressed_rag=rag_result.get("compressed_text", ""),
            reason_label="OPENCODE_WORKER",
        )
    elif decision["route"] == "HOMELAB_RAG":
        out = execute_local_worker(
            query=query,
            memory_mgr=memory_mgr,
            rag_result=rag_result,
            route_name="HOMELAB_RAG",
            model=DEFAULT_MODEL,
        )
    else:
        out = execute_local_worker(
            query=query,
            memory_mgr=memory_mgr,
            rag_result=rag_result,
            route_name="WORKER_LOCAL_GPU",
            model=DEFAULT_MODEL,
        )

    # 5. Registro na Memória Episódica (Hy-Memory Short-Term WorkingFact)
    memory_mgr.record_turn(
        query=query,
        route=decision["route"],
        thinking=decision["thinking"],
        reason=decision["reason"],
        sources=rag_result.get("sources", []),
    )


if __name__ == "__main__":
    main()
