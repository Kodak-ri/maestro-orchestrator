#!/usr/bin/env python3
"""
Suíte de Testes Automatizados — Maestro v2.0 (CLI + Router + Hy-Memory + Super-Prompt + Open WebUI Pipe)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.memory import HybridMemoryManager, compress_context_for_token_budget
from src.router import HybridCascadeRouter, estimate_thinking_level
from src.super_prompt import build_surgical_super_prompt, resolve_canonical_stacks
from src.maestro_openwebui_pipe import Pipe


class TestMaestroV2Suite(unittest.TestCase):
    def setUp(self):
        self.tmp_mem = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp_mem.close()
        os.unlink(self.tmp_mem.name)
        self.memory_mgr = HybridMemoryManager(memory_file=self.tmp_mem.name, max_episodic_turns=6, inject_recent_turns=3)
        self.router = HybridCascadeRouter(enable_dense_embeddings=False, enable_llm_fallback=False)

    def tearDown(self):
        if os.path.exists(self.tmp_mem.name):
            os.unlink(self.tmp_mem.name)

    def test_01_hybrid_cascade_routing_accuracy_and_latency(self):
        """Valida acurácia nas 4 rotas e latência sub-50ms."""
        cases = [
            ("Crie um script em Python para ordenar um arquivo CSV grande", "WORKER_LOCAL_GPU"),
            ("Gere um Dockerfile multi-stage para uma API FastAPI com Gunicorn", "WORKER_LOCAL_GPU"),
            ("Use o opencode para refatorar múltiplos arquivos do projeto e comparar benchmarks no HuggingFace", "OPENCODE_WORKER"),
            ("Qual é o caminho canônico da pasta viva no pool_koda e quanta RAM tem o servidor OMV?", "HOMELAB_RAG"),
            ("Quais portas usam o protocolo SSAP na Smart TV LG webOS kodachi?", "HOMELAB_RAG"),
            ("Conecte via ssh omv e execute sudo agente-docker ps para diagnosticar o container immich", "CIRURGIAO_AGY"),
            ("Homologue a stack romm-stack na labvm e faça git push para deploy no Komodo", "CIRURGIAO_AGY"),
            ("Utilize o agy para revisar todos os repositórios do GitHub e padronizar o README", "CIRURGIAO_AGY"),
        ]
        for query, expected_route in cases:
            dec = self.router.route(query)
            self.assertEqual(
                dec["route"],
                expected_route,
                f"Falha na query '{query}': esperado {expected_route}, obtido {dec['route']}",
            )
            self.assertLess(dec["latency_ms"], 50.0, f"Latência acima de 50ms: {dec['latency_ms']}ms")

    def test_02_multi_turn_session_affinity(self):
        """Valida afinidade de sessão em perguntas curtas de continuação (LiteLLM v2 / Pi pattern)."""
        dec = self.router.route("E como fica o backup disso?", last_route="HOMELAB_RAG")
        self.assertEqual(dec["route"], "HOMELAB_RAG")

    def test_03_thinking_level_calibration(self):
        """Valida recomendação automática de thinking level (low, medium, high)."""
        t_low = estimate_thinking_level("Crie uma função soma em python", "WORKER_LOCAL_GPU")
        t_high = estimate_thinking_level(
            "Realize uma auditoria forense completa na arquitetura MergerFS fstab, swapfile e migração multi-repositório no OMV",
            "CIRURGIAO_AGY",
        )
        self.assertEqual(t_low, "low")
        self.assertEqual(t_high, "high")

    def test_04_hy_memory_episodic_compaction_and_rag_compression(self):
        """Valida WorkingFacts, compactação estilo Pi e compressão de contexto RAG estilo Hy-Memory/LLMLingua."""
        for i in range(8):
            self.memory_mgr.record_turn(
                query=f"Ajustar stack media-stack em /srv/mergerfs/pool_koda/docker_data/media turno {i}",
                route="CIRURGIAO_AGY",
                thinking="medium",
                reason="Teste de compactação",
                sources=["DOCUMENTACAO_COMPLETA_OMV.md"],
            )
        # Como max_episodic_turns=6 e inject_recent_turns=3, deve ter compactado automaticamente
        self.assertGreaterEqual(self.memory_mgr.state["compactions_count"], 1)
        self.assertTrue(len(self.memory_mgr.state["compaction_summary"]) > 10)

        rag_res = self.memory_mgr.retrieve_semantic_rag(
            "Configuração do MergerFS pool_koda, rede kodak-net e RAM de 7.6 GiB no OMV",
            max_sections=3,
            max_chars_budget=900,
        )
        self.assertGreater(len(rag_res["sections"]), 0)
        self.assertGreater(rag_res["metrics"]["saved_pct"], 25.0)

    def test_05_super_prompt_5_pillars_and_coordinates(self):
        """Valida se o Super-Prompt injeta coordenadas canônicas e os 5 pilares do Orca."""
        query = "Homologue a stack immich e komodo na labvm e atualize o repositório GitOps"
        stacks = resolve_canonical_stacks(query)
        stack_names = [s["project_name"] for s in stacks]
        self.assertIn("immich", stack_names)
        self.assertIn("komodo", stack_names)

        dec = self.router.route(query)
        rag_res = self.memory_mgr.retrieve_semantic_rag(query, max_sections=2)
        ep_ctx = self.memory_mgr.get_episodic_context(query)
        sp = build_surgical_super_prompt(query, dec, rag_res, ep_ctx)

        self.assertIn("/srv/mergerfs/pool_koda/docker_data/immich/", sp)
        self.assertIn("kodak-net", sp)
        self.assertIn("sudo agente-ler", sp)
        self.assertIn("7.6 GiB", sp)
        self.assertIn("<IP_SERVIDOR>", sp)

    def test_06_openwebui_pipe_v2_manifold(self):
        """Valida o Manifold Pipe v2.0 do Open WebUI."""
        pipe = Pipe()
        models = pipe.pipes()
        self.assertEqual(len(models), 4)
        ids = [m["id"] for m in models]
        self.assertEqual(ids, ["auto", "coder", "rag", "agy"])

        # Teste de geração de Super-Prompt via Pipe
        body = {
            "model": "maestro.auto",
            "messages": [
                {"role": "user", "content": "Conecte via ssh labvm, teste a stack romm-stack e faça git push"}
            ],
        }
        out = pipe.pipe(body)
        self.assertIsInstance(out, str)
        self.assertIn("CIRURGIAO_AGY", out)
        self.assertIn("romm-stack", out)

        # Teste de Pi-Compaction de histórico longo no Pipe
        long_msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"Mensagem turno {i}"} for i in range(16)]
        compacted, count = pipe._compact_chat_history(long_msgs)
        self.assertGreater(count, 0)
        self.assertLess(len(compacted), len(long_msgs))

    def test_07_ollama_streaming_telemetry_simulation(self):
        """Valida o motor de streaming NDJSON e cálculo de tokens/s do Ollama (RTX 3060 Ti)."""
        import http.server
        import json
        import threading

        class MockOllamaHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                if self.path == "/api/tags":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"models": [{"name": "kodak-coder:latest"}]}).encode())
                elif self.path == "/api/ps":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"models": [{"name": "kodak-coder:latest", "size_vram": 5046586572}]}).encode())

            def do_POST(self):
                if self.path == "/api/chat":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    chunks = [
                        {"message": {"content": "print('OK')"}, "done": False},
                        {"message": {"content": ""}, "done": True, "eval_count": 70, "eval_duration": 1000000000},
                    ]
                    for c in chunks:
                        self.wfile.write((json.dumps(c) + "\n").encode())

        server = http.server.HTTPServer(("127.0.0.1", 0), MockOllamaHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            pipe = Pipe()
            pipe.valves.OLLAMA_BASE_URL = f"http://127.0.0.1:{port}"
            body = {
                "model": "maestro.coder",
                "messages": [{"role": "user", "content": "Crie um hello world em python"}],
            }
            gen = pipe.pipe(body)
            output = "".join(list(gen))
            self.assertIn("print('OK')", output)
            self.assertIn("70.0 tokens/s", output)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

